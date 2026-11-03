from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session, login_limiter
from app.models import AuditLog, User, UserSession, utcnow
from app.security import hash_password, hash_token, new_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool


class Me(BaseModel):
    username: str
    csrf_token: str


def _start_session(
    db: Session, response: Response, user: User, settings: Settings
) -> UserSession:
    token = new_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(),
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.commit()

    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return session


def _audit(db: Session, user_id: int | None, action: str, **detail) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity="user", detail=detail or None))
    db.commit()


@router.get("/status", response_model=AuthStatus)
def auth_status(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthStatus:
    user_count = db.scalar(select(func.count()).select_from(User)) or 0

    authenticated = False
    if request.cookies.get(settings.cookie_name):
        try:
            get_current_session(request, db, settings)
            authenticated = True
        except HTTPException:
            authenticated = False

    return AuthStatus(setup_required=user_count == 0, authenticated=authenticated)


@router.post("/setup", response_model=Me, status_code=status.HTTP_201_CREATED)
def setup(
    body: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Me:
    """Create the single user. Only allowed while no user exists."""
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")

    if len(body.password) < settings.min_password_length:
        raise HTTPException(
            422,  # literal: Starlette renamed the constant between versions
            f"Password must be at least {settings.min_password_length} characters",
        )

    user = User(username=body.username.strip(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")

    _audit(db, user.id, "user.setup")
    session = _start_session(db, response, user, settings)
    return Me(username=user.username, csrf_token=session.csrf_token)


@router.post("/login", response_model=Me)
def login(
    body: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Me:
    key = body.username.strip().lower()

    if login_limiter.is_blocked(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(settings.login_window_s)},
        )

    user = db.scalar(select(User).where(User.username == body.username.strip()))

    if not verify_password(user.password_hash if user else None, body.password):
        login_limiter.record_failure(key)
        _audit(db, user.id if user else None, "user.login_failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    login_limiter.reset(key)
    _audit(db, user.id, "user.login")
    session = _start_session(db, response, user, settings)
    return Me(username=user.username, csrf_token=session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    _audit(db, session.user_id, "user.logout")
    db.delete(session)
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Change the password; every other signed-in session is ended."""
    user = session.user
    if not verify_password(user.password_hash, body.current_password):
        _audit(db, user.id, "user.password_change_failed")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    if len(body.new_password) < settings.min_password_length:
        raise HTTPException(
            422, f"Password must be at least {settings.min_password_length} characters"
        )
    if body.new_password == body.current_password:
        raise HTTPException(422, "The new password must differ from the current one")

    user.password_hash = hash_password(body.new_password)
    others = db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id, UserSession.id != session.id
        )
    ).all()
    for other in others:
        db.delete(other)
    db.commit()
    _audit(db, user.id, "user.password_changed", sessions_ended=len(others))


@router.get("/me", response_model=Me)
def me(session: UserSession = Depends(get_current_session)) -> Me:
    return Me(username=session.user.username, csrf_token=session.csrf_token)
