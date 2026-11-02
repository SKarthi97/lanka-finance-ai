import os
from pathlib import Path

from app.config import Settings


def document_relpath(user_id: int, sha256: str) -> str:
    return f"{user_id}/{sha256}.pdf"


def resolve(settings: Settings, relpath: str) -> Path:
    """Absolute path of a stored document. Refuses anything outside DOCUMENTS_DIR."""
    base = Path(settings.documents_dir).resolve()
    path = (base / relpath).resolve()
    if base not in path.parents:
        raise ValueError("Path escapes the documents directory")
    return path


def save_document(settings: Settings, relpath: str, data: bytes) -> bool:
    """Write atomically. Returns True if the file was newly created."""
    path = resolve(settings, relpath)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return not existed


def remove_document(settings: Settings, relpath: str) -> None:
    resolve(settings, relpath).unlink(missing_ok=True)
