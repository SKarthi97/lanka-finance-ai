from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import notifications

router = APIRouter(prefix="/api", tags=["notifications"])


class NoticeOut(BaseModel):
    key: str
    kind: str
    severity: str
    text: str
    href: str


class NotificationsOut(BaseModel):
    count: int
    items: list[NoticeOut]


@router.get("/notifications", response_model=NotificationsOut)
def list_notifications(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> NotificationsOut:
    """What needs attention right now. Derived from the data; nothing to mark as read."""
    items = [
        NoticeOut(key=n.key, kind=n.kind, severity=n.severity, text=n.text, href=n.href)
        for n in notifications.collect(db, session.user_id)
    ]
    return NotificationsOut(count=len(items), items=items)
