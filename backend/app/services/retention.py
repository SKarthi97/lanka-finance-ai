from sqlalchemy.orm import Session

from app import storage
from app.config import Settings
from app.models import Document, utcnow


def discard_stored_file(db: Session, document: Document, settings: Settings) -> bool:
    """Delete the stored PDF unless retention is on. Returns True if a file was removed.

    Call this only when a document has reached a successful terminal state. Failed
    documents keep their file so they can be retried.
    """
    if settings.retain_documents or document.file_deleted_at is not None:
        return False

    storage.remove_document(settings, document.storage_path)
    document.file_deleted_at = utcnow()
    db.commit()
    return True
