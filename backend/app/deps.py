import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import UserSession
from app.security import LoginRateLimiter, as_utc, hash_token

_settings = get_settings()

login_limiter = LoginRateLimiter(
    max_attempts=_settings.login_max_attempts,
    window_s=_settings.login_window_s,
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserSession:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if session is None or as_utc(session.expires_at) <= datetime.now(timezone.utc):
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    # CSRF: every state-changing request must echo the per-session token.
    if request.method not in SAFE_METHODS:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")

    return session
