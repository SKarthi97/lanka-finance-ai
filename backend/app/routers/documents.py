import hashlib
import logging
from datetime import date, datetime
from decimal import Decimal

import pymupdf
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import storage
from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.job_queue import enqueue
from app.models import AuditLog, Bank, Document, DocumentPage, Job, Transaction, UserSession
from app.services.retention import discard_stored_file

log = logging.getLogger("documents")

router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    original_filename: str
    sha256: str
    size_bytes: int
    page_count: int | None
    is_encrypted: bool
    status: str
    error: str | None
    bank_code: str | None
    file_available: bool
    created_at: datetime


class PageOut(BaseModel):
    page_no: int
    kind: str
    char_count: int


class DocumentDetail(DocumentOut):
    pages: list[PageOut]
    account_last4: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    adapter: str | None
    adapter_version: str | None
    extraction_confidence: float | None
    validation: dict | None
    transaction_count: int


def _error(status: int, code: str, message: str, **extra) -> HTTPException:
    # Code only: never filenames, contents or passwords.
    log.info("request rejected: %s (%s)", code, status)
    return HTTPException(status, detail={"code": code, "message": message, **extra})


def _duplicate(existing: Document | None) -> HTTPException:
    """409 that says which stored document matched, so the user can tell why."""
    return _error(
        409,
        "duplicate",
        "This exact file has already been uploaded.",
        document_id=existing.id if existing else None,
        original_filename=existing.original_filename if existing else None,
        uploaded_at=existing.created_at.isoformat() if existing else None,
        document_status=existing.status if existing else None,
    )


def _to_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        original_filename=document.original_filename,
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        is_encrypted=document.is_encrypted,
        status=document.status,
        error=document.error,
        bank_code=document.bank.code if document.bank else None,
        file_available=document.file_deleted_at is None,
        created_at=document.created_at,
    )


@router.post("", response_model=DocumentOut, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    password: str | None = Form(default=None),
    bank_code: str | None = Form(default=None),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    """Accept a PDF statement and queue it for processing.

    Order (docs/00-architecture.md section 5): size and magic-byte checks, sha256
    duplicate check, password check for encrypted files, then store and enqueue.
    The PDF password is used only to open the file in this request. It is never
    stored, logged or placed in a job payload.
    """
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise _error(413, "too_large", f"File exceeds {settings.max_upload_mb} MB.")
    if not data.startswith(b"%PDF-"):
        raise _error(415, "not_pdf", "Only PDF files are accepted.")

    sha256 = hashlib.sha256(data).hexdigest()
    user_id = session.user_id

    existing = db.scalar(
        select(Document).where(Document.user_id == user_id, Document.sha256 == sha256)
    )
    if existing:
        raise _duplicate(existing)

    bank = None
    if bank_code:
        bank = db.scalar(select(Bank).where(Bank.code == bank_code))
        if bank is None:
            raise _error(422, "unknown_bank", "Unsupported bank.")

    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 - any parser failure means "not a usable PDF"
        raise _error(422, "unreadable_pdf", "This file could not be read as a PDF.")

    try:
        encrypted = bool(pdf.needs_pass)
        if encrypted:
            if not password:
                raise _error(422, "password_required", "This PDF is password protected.")
            if not pdf.authenticate(password):
                raise _error(422, "password_incorrect", "Incorrect PDF password.")
            # Keep a decrypted copy so the worker never needs the password.
            stored = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
        else:
            stored = data
        page_count = pdf.page_count
    finally:
        pdf.close()

    if page_count > settings.max_pages:
        raise _error(422, "too_many_pages", f"PDF exceeds {settings.max_pages} pages.")
    if page_count == 0:
        raise _error(422, "empty_pdf", "This PDF has no pages.")

    relpath = storage.document_relpath(user_id, sha256)
    created_file = storage.save_document(settings, relpath, stored)

    document = Document(
        user_id=user_id,
        bank_id=bank.id if bank else None,
        sha256=sha256,
        storage_path=relpath,
        original_filename=(file.filename or "statement.pdf")[:255],
        size_bytes=len(data),
        page_count=page_count,
        is_encrypted=encrypted,
        status="queued",
    )
    db.add(document)
    try:
        db.flush()
        enqueue(
            db,
            "inspect_document",
            document_id=document.id,
            max_attempts=settings.job_max_attempts,
        )
        db.add(
            AuditLog(
                user_id=user_id,
                action="document.upload",
                entity="document",
                entity_id=str(document.id),
                detail={"sha256": sha256[:12], "encrypted": encrypted},
            )
        )
        db.commit()
    except IntegrityError:
        # Lost a race with an identical concurrent upload.
        db.rollback()
        if created_file:
            storage.remove_document(settings, relpath)
        winner = db.scalar(
            select(Document).where(
                Document.user_id == user_id, Document.sha256 == sha256
            )
        )
        raise _duplicate(winner)
    except Exception:
        db.rollback()
        if created_file:
            storage.remove_document(settings, relpath)
        raise

    return _to_out(document)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    rows = db.scalars(
        select(Document)
        .where(Document.user_id == session.user_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(200)
    ).all()
    return [_to_out(row) for row in rows]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    document = db.get(Document, document_id)
    if document is None or document.user_id != session.user_id:
        raise _error(404, "not_found", "Document not found.")

    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_no)
    ).all()

    transaction_count = db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.document_id == document.id
        )
    )

    return DocumentDetail(
        **_to_out(document).model_dump(),
        pages=[
            PageOut(page_no=p.page_no, kind=p.kind, char_count=p.char_count)
            for p in pages
        ],
        account_last4=document.account.account_number_last4 if document.account else None,
        period_start=document.period_start,
        period_end=document.period_end,
        opening_balance=document.opening_balance,
        closing_balance=document.closing_balance,
        adapter=document.adapter,
        adapter_version=document.adapter_version,
        extraction_confidence=document.extraction_confidence,
        validation=document.validation,
        transaction_count=transaction_count or 0,
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Remove an upload so the same file can be uploaded again."""
    document = db.get(Document, document_id)
    if document is None or document.user_id != session.user_id:
        raise _error(404, "not_found", "Document not found.")
    if document.status == "processing":
        raise _error(409, "busy", "This document is being processed. Try again shortly.")

    relpath = document.storage_path
    db.add(
        AuditLog(
            user_id=session.user_id,
            action="document.delete",
            entity="document",
            entity_id=str(document.id),
            detail={"sha256": document.sha256[:12]},
        )
    )
    # Explicit, so behaviour does not depend on database-level cascades.
    db.execute(delete(Job).where(Job.document_id == document.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    db.execute(delete(Transaction).where(Transaction.document_id == document.id))
    db.delete(document)
    db.commit()

    storage.remove_document(settings, relpath)


@router.post("/{document_id}/accept", response_model=DocumentOut)
def accept_document(
    document_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    """The user reviewed a statement that failed reconciliation and accepts it.

    Accepted statements count in analytics (docs/00-architecture.md section 8.6).
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != session.user_id:
        raise _error(404, "not_found", "Document not found.")
    if document.status != "needs_review":
        raise _error(409, "not_reviewable", "Only statements needing review can be accepted.")

    document.status = "accepted"
    db.add(
        AuditLog(
            user_id=session.user_id,
            action="document.accept",
            entity="document",
            entity_id=str(document.id),
            detail={"issues": len((document.validation or {}).get("issues", []))},
        )
    )
    db.commit()
    discard_stored_file(db, document, settings)
    return _to_out(document)


@router.get("/{document_id}/pages/{page_no}/image")
def page_image(
    document_id: int,
    page_no: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Render one page of the stored original, for checking a row against its source.

    Only available while the file is retained (statements needing review always are).
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != session.user_id:
        raise _error(404, "not_found", "Document not found.")

    path = storage.resolve(settings, document.storage_path)
    if document.file_deleted_at is not None or not path.exists():
        raise _error(404, "file_not_retained", "The original file is no longer stored.")

    pdf = pymupdf.open(path)
    try:
        if not 1 <= page_no <= pdf.page_count:
            raise _error(404, "page_not_found", "Page not found.")
        png = pdf[page_no - 1].get_pixmap(dpi=110).tobytes("png")
    finally:
        pdf.close()

    return Response(
        png, media_type="image/png", headers={"Cache-Control": "private, no-store"}
    )


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=202)
def reprocess_document(
    document_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    """Run extraction again on the stored original, e.g. after a parser improvement.

    Needs the original file (kept for statements that need review or failed, or when
    RETAIN_DOCUMENTS=true). The previous transactions are replaced, not duplicated.
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != session.user_id:
        raise _error(404, "not_found", "Document not found.")
    if document.status in ("queued", "processing", "inspected"):
        raise _error(409, "busy", "This document is already being processed.")
    if document.status == "accepted":
        raise _error(409, "already_accepted", "Accepted statements cannot be re-run.")

    path = storage.resolve(settings, document.storage_path)
    if document.file_deleted_at is not None or not path.exists():
        raise _error(409, "file_not_retained", "The original file is no longer stored.")

    document.status = "queued"
    document.error = None
    enqueue(
        db,
        "extract_transactions",
        document_id=document.id,
        max_attempts=settings.job_max_attempts,
    )
    db.add(
        AuditLog(
            user_id=session.user_id,
            action="document.reprocess",
            entity="document",
            entity_id=str(document.id),
        )
    )
    db.commit()
    return _to_out(document)
