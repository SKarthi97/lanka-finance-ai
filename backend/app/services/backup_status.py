"""Whether your data has been backed up lately, and how much room it takes.

The backup scripts run on the computer, outside the app, and record each successful backup in the
settings table (a time, a size and two flags: nothing about the contents). The app only reads that
record. It cannot see the backup folder, so a backup you copied away or deleted by hand still counts
as made.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, Setting, Transaction
from app.tuning import BACKUP_STALE_DAYS

KEY = "last_backup"


def record(db: Session, at: datetime, size_kb: int, encrypted: bool, verified: bool) -> None:
    value = {"at": at.astimezone(UTC).isoformat(), "size_kb": size_kb, "encrypted": encrypted, "verified": verified}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value


def status(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    row = db.get(Setting, KEY)
    if row is None or not isinstance(row.value, dict) or "at" not in row.value:
        return {"recorded": False, "at": None, "age_days": None, "size_kb": None, "encrypted": None, "verified": None, "stale": True}
    when = datetime.fromisoformat(row.value["at"])
    age = max((today - when.astimezone().date()).days, 0)
    return {
        "recorded": True,
        "at": when.isoformat(),
        "age_days": age,
        "size_kb": row.value.get("size_kb"),
        "encrypted": row.value.get("encrypted"),
        "verified": row.value.get("verified"),
        "stale": age > BACKUP_STALE_DAYS,
    }


def has_data(db: Session, user_id: int) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Document).where(Document.user_id == user_id)))


def _folder_size(path: Path) -> tuple[int, int]:
    total = files = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                total += item.stat().st_size
    return total, files


def storage(db: Session, settings: Settings, user_id: int) -> dict:
    database = None
    if db.get_bind().dialect.name == "postgresql":
        database = db.scalar(text("SELECT pg_database_size(current_database())"))
    documents_bytes, documents_files = _folder_size(Path(settings.documents_dir))
    return {
        "database_bytes": database,
        "documents_bytes": documents_bytes,
        "documents_files": documents_files,
        "statements": db.scalar(select(func.count()).select_from(Document).where(Document.user_id == user_id)) or 0,
        "transactions": db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == user_id)) or 0,
        "backup": status(db),
    }
