"""Stages 2-6 of the PDF pipeline: adapter extraction, validation, persistence.

Privacy: nothing in here logs statement text, amounts or account numbers. Failures are
raised as short codes. The full account number exists only in local variables and is
reduced to last4 + fingerprint immediately.
"""

import hashlib
import logging
import time
from datetime import timedelta

import pymupdf
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import storage
from app.adapters.base import ParsedStatement, ParseError
from app.adapters.registry import select_adapter
from app.config import Settings
from app.job_queue import PermanentJobError
from app.models import Bank, Document, Job, Transaction
from app.services.accounts import get_or_create_account
from app.services.retention import discard_stored_file
from app.services.validation import ValidationResult, validate

log = logging.getLogger("extraction")

ACTIVE_STATUSES = ("reconciled", "accepted")


def _normalise(description: str) -> str:
    return " ".join(description.upper().split())


def row_hash(account_id: int | None, tx) -> str:
    key = "|".join(
        [
            str(account_id or ""),
            tx.date.isoformat(),
            str(tx.debit),
            str(tx.credit),
            str(tx.balance),
            _normalise(tx.description),
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def extract_transactions(db: Session, job: Job, settings: Settings) -> None:
    document = db.get(Document, job.document_id) if job.document_id else None
    if document is None:
        raise PermanentJobError("document_missing")

    document.status = "processing"
    document.error = None
    db.commit()

    path = storage.resolve(settings, document.storage_path)
    if not path.exists():
        raise PermanentJobError("file_missing")

    deadline = time.monotonic() + settings.job_timeout_s
    pages: list[str] = []
    pdf = pymupdf.open(path)
    try:
        if pdf.needs_pass:
            raise PermanentJobError("file_encrypted")
        for page in pdf:
            if time.monotonic() > deadline:
                raise TimeoutError("Extraction exceeded the time limit")
            pages.append(page.get_text("text"))
    finally:
        pdf.close()

    if not any(text.strip() for text in pages):
        raise PermanentJobError("no_text_layer")  # scanned: OCR arrives in a later phase

    bank_code = document.bank.code if document.bank else None
    adapter = select_adapter(pages, bank_code)
    if adapter is None:
        raise PermanentJobError("unsupported_layout")

    try:
        parsed = adapter.parse(pages)
    except ParseError as error:
        raise PermanentJobError(error.code) from None

    result = validate(parsed)
    _persist(db, document, parsed, result, settings)

    # Statistics only: counts and ids.
    log.info(
        "document %s: adapter=%s rows=%s reconciled=%s",
        document.id,
        parsed.adapter,
        len(parsed.transactions),
        result.reconciled,
    )

    # Keep the file for statements that need a human look; drop it once reconciled.
    if document.status == "reconciled":
        discard_stored_file(db, document, settings)


def _persist(
    db: Session,
    document: Document,
    parsed: ParsedStatement,
    result: ValidationResult,
    settings: Settings,
) -> None:
    if document.bank_id is None:
        bank = db.scalar(select(Bank).where(Bank.code == parsed.bank_code))
        document.bank_id = bank.id if bank else None

    account = None
    if parsed.account_number:
        account = get_or_create_account(
            db, settings, document.user_id, document.bank_id, parsed.account_number
        )
    parsed.account_number = None  # drop the sensitive value as early as possible
    document.account_id = account.id if account else None

    db.execute(delete(Transaction).where(Transaction.document_id == document.id))
    for tx in parsed.transactions:
        db.add(
            Transaction(
                user_id=document.user_id,
                document_id=document.id,
                account_id=document.account_id,
                bank_id=document.bank_id,
                seq=tx.seq,
                transaction_date=tx.date,
                original_description=tx.description,
                debit=tx.debit,
                credit=tx.credit,
                running_balance=tx.balance,
                source_page=tx.page_no,
                validation_status=result.row_status.get(tx.seq, "ok"),
                row_hash=row_hash(document.account_id, tx),
            )
        )

    document.period_start = parsed.period_start
    document.period_end = parsed.statement_date
    document.opening_balance = parsed.opening_balance
    document.closing_balance = parsed.closing_balance
    document.adapter = parsed.adapter
    document.adapter_version = parsed.adapter_version
    document.extraction_confidence = result.confidence
    document.validation = {
        "reconciled": result.reconciled,
        "checks": result.checks,
        "issues": [
            {"code": i.code, "page": i.page, "seq": i.seq} for i in result.issues
        ],
    }
    document.status = "reconciled" if result.reconciled else "needs_review"
    db.flush()

    _check_continuity(db, document)
    db.commit()


def _check_continuity(db: Session, document: Document) -> None:
    """Cross-statement checks (doc section 8, item 4): this statement should start
    where the previous one for the same account ended. Reported, never blocking."""
    if document.account_id is None or document.period_end is None:
        return

    previous = db.scalar(
        select(Document)
        .where(
            Document.user_id == document.user_id,
            Document.account_id == document.account_id,
            Document.id != document.id,
            Document.period_end < document.period_end,
            Document.status.in_(ACTIVE_STATUSES + ("needs_review",)),
        )
        .order_by(Document.period_end.desc())
        .limit(1)
    )
    if previous is None:
        return

    # Copy: mutating the stored list in place would hide the change from SQLAlchemy.
    issues = list(document.validation["issues"])
    if (
        previous.closing_balance is not None
        and document.opening_balance is not None
        and previous.closing_balance != document.opening_balance
    ):
        issues.append({"code": "opening_balance_gap", "page": None, "seq": None})
    if document.period_start is not None:
        if document.period_start < previous.period_end:
            issues.append({"code": "period_overlap", "page": None, "seq": None})
        elif document.period_start > previous.period_end + timedelta(days=1):
            issues.append({"code": "period_gap", "page": None, "seq": None})

    # JSON columns need reassignment to register the change.
    document.validation = {**document.validation, "issues": issues}
