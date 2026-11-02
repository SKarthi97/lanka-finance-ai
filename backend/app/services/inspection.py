"""Stage 1 of the PDF pipeline (docs/00-architecture.md section 5): classify each page.

Deterministic only. No text content is logged or stored, just counts and a kind.
"""

import time

import pymupdf
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import storage
from app.config import Settings
from app.models import Document, DocumentPage, Job
from app.services.retention import discard_stored_file

MIN_TEXT_CHARS = 30


def classify_page(char_count: int, image_count: int) -> str:
    if char_count >= MIN_TEXT_CHARS:
        return "mixed" if image_count else "text"
    return "scanned" if image_count else "empty"


def inspect_document(db: Session, job: Job, settings: Settings) -> None:
    document = db.get(Document, job.document_id) if job.document_id else None
    if document is None:
        raise ValueError("Document not found for job")

    document.status = "processing"
    document.error = None
    db.commit()

    deadline = time.monotonic() + settings.job_timeout_s
    path = storage.resolve(settings, document.storage_path)

    pages: list[DocumentPage] = []
    pdf = pymupdf.open(path)
    try:
        if pdf.needs_pass:
            raise ValueError("Stored PDF is still encrypted")
        if pdf.page_count > settings.max_pages:
            raise ValueError("Page limit exceeded")

        for index, page in enumerate(pdf, start=1):
            if time.monotonic() > deadline:
                raise TimeoutError("Inspection exceeded the time limit")
            char_count = len("".join(page.get_text("text").split()))
            pages.append(
                DocumentPage(
                    document_id=document.id,
                    page_no=index,
                    kind=classify_page(char_count, len(page.get_images())),
                    char_count=char_count,
                )
            )
    finally:
        pdf.close()

    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    db.add_all(pages)
    document.page_count = len(pages)
    document.status = "inspected"
    db.commit()

    # "inspected" is the last pipeline stage for now. When transaction extraction is
    # added (Phase 2), move this call to the end of that job instead, so the file
    # survives until it has been read.
    discard_stored_file(db, document, settings)
