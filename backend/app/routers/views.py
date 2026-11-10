from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import SavedView, UserSession

router = APIRouter(prefix="/api/views", tags=["views"])

MAX_VIEWS = 50


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class ViewFilters(BaseModel):
    """The Transactions filters a view may hold. Anything else is rejected, so a view can
    never carry more than filter values."""

    model_config = {"extra": "forbid"}

    q: str | None = Field(default=None, max_length=128)
    bank_code: str | None = Field(default=None, max_length=32)
    category_id: int | None = None
    uncategorised: bool = False
    year: int | None = Field(default=None, ge=2000, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    flagged: bool = False
    duplicates: Literal["hide", "show", "only"] = "hide"
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    direction: Literal["in", "out"] | None = None


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    filters: ViewFilters


class ViewOut(BaseModel):
    id: int
    name: str
    filters: ViewFilters


def _out(view: SavedView) -> ViewOut:
    return ViewOut(id=view.id, name=view.name, filters=ViewFilters(**view.filters))


@router.get("", response_model=list[ViewOut])
def list_views(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> list[ViewOut]:
    views = db.scalars(
        select(SavedView).where(SavedView.user_id == session.user_id).order_by(SavedView.name)
    ).all()
    return [_out(v) for v in views]


@router.post("", response_model=ViewOut, status_code=201)
def save_view(
    body: ViewIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ViewOut:
    """Save the filters under a name. Saving under an existing name replaces that view."""
    name = body.name.strip()
    if not name:
        raise _error(422, "name_required", "Give the view a name.")
    values = body.filters.model_dump(mode="json", exclude_defaults=True)

    view = db.scalar(
        select(SavedView).where(SavedView.user_id == session.user_id, SavedView.name == name)
    )
    if view is None:
        count = len(db.scalars(select(SavedView.id).where(SavedView.user_id == session.user_id)).all())
        if count >= MAX_VIEWS:
            raise _error(409, "too_many_views", f"At most {MAX_VIEWS} saved views.")
        view = SavedView(user_id=session.user_id, name=name, filters=values)
        db.add(view)
    else:
        view.filters = values
    try:
        db.commit()
    except IntegrityError:  # two saves of one name at once
        db.rollback()
        raise _error(409, "name_taken", "A view with that name already exists.") from None
    db.refresh(view)
    return _out(view)


@router.delete("/{view_id}", status_code=204)
def delete_view(
    view_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    view = db.get(SavedView, view_id)
    if view is None or view.user_id != session.user_id:
        raise _error(404, "not_found", "View not found.")
    db.delete(view)
    db.commit()
