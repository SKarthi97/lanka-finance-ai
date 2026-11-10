from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import (
    Category,
    ClassificationRule,
    Transaction,
    UserSession,
)
from app.services import categorizer

router = APIRouter(prefix="/api", tags=["categories"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _category_or_404(db: Session, user_id: int, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None or category.user_id != user_id:
        raise _error(404, "category_not_found", "Category not found.")
    return category


# --- categories -------------------------------------------------------------------------------


class CategoryOut(BaseModel):
    id: int
    name: str
    kind: str
    is_system: bool
    transactions: int
    parent_id: int | None = None
    full_name: str = ""  # "Parent › Child" for a sub-category, else the name


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["income", "expense", "transfer"]
    parent_id: int | None = None  # one level only: a sub-category of a top-level category of the same kind


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: int | None = None
    set_parent: bool = False  # true: apply parent_id (None makes it top-level again)


def _full_name(category: Category, by_id: dict[int, Category]) -> str:
    parent = by_id.get(category.parent_id) if category.parent_id else None
    return f"{parent.name} › {category.name}" if parent else category.name


def _check_parent(db: Session, user_id: int, parent_id: int, kind: str, own_id: int | None) -> None:
    """A sub-category hangs under a top-level category of the same kind (one level, no loops)."""
    parent = _category_or_404(db, user_id, parent_id)
    if parent.parent_id is not None:
        raise _error(422, "parent_is_sub", "Choose a top-level category as the parent: only one level is allowed.")
    if parent.kind != kind:
        raise _error(422, "parent_kind", "A sub-category must have the same kind (income, expense, transfer) as its parent.")
    if own_id is not None and parent.id == own_id:
        raise _error(422, "parent_self", "A category cannot be its own parent.")


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> list[CategoryOut]:
    categorizer.ensure_defaults(db, session.user_id)
    db.commit()

    counts = dict(
        db.execute(
            select(Transaction.category_id, func.count())
            .where(Transaction.user_id == session.user_id, Transaction.is_duplicate.is_(False))
            .group_by(Transaction.category_id)
        ).all()
    )
    categories = db.scalars(
        select(Category).where(Category.user_id == session.user_id).order_by(Category.kind, Category.name)
    ).all()
    by_id = {c.id: c for c in categories}
    return [
        CategoryOut(
            id=c.id,
            name=c.name,
            kind=c.kind,
            is_system=c.is_system,
            transactions=counts.get(c.id, 0),
            parent_id=c.parent_id,
            full_name=_full_name(c, by_id),
        )
        for c in categories
    ]


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(
    body: CategoryIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> CategoryOut:
    categorizer.ensure_defaults(db, session.user_id)
    if body.parent_id is not None:
        _check_parent(db, session.user_id, body.parent_id, body.kind, None)
    category = Category(user_id=session.user_id, name=body.name.strip(), kind=body.kind, parent_id=body.parent_id)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(409, "duplicate_category", "A category with that name already exists.") from None
    parent = db.get(Category, category.parent_id) if category.parent_id else None
    return CategoryOut(
        id=category.id,
        name=category.name,
        kind=category.kind,
        is_system=False,
        transactions=0,
        parent_id=category.parent_id,
        full_name=f"{parent.name} › {category.name}" if parent else category.name,
    )


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryPatch,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> CategoryOut:
    """Rename a category you made, or move it under (or out of) a parent. Built-in categories keep
    their names: reports, interest and tax figures find them by name."""
    category = _category_or_404(db, session.user_id, category_id)
    if category.is_system:
        raise _error(409, "system_category", "Built-in categories cannot be renamed or moved.")
    if body.name is not None:
        category.name = body.name.strip()
    if body.set_parent:
        if body.parent_id is not None:
            _check_parent(db, session.user_id, body.parent_id, category.kind, category.id)
            has_children = db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == category.id))
            if has_children:
                raise _error(422, "has_children", "This category has sub-categories, so it cannot become one itself.")
        category.parent_id = body.parent_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(409, "duplicate_category", "A category with that name already exists.") from None
    parent = db.get(Category, category.parent_id) if category.parent_id else None
    count = db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.category_id == category.id, Transaction.is_duplicate.is_(False))
    )
    return CategoryOut(
        id=category.id,
        name=category.name,
        kind=category.kind,
        is_system=False,
        transactions=count or 0,
        parent_id=category.parent_id,
        full_name=f"{parent.name} › {category.name}" if parent else category.name,
    )


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    category = _category_or_404(db, session.user_id, category_id)
    if category.is_system:
        raise _error(409, "system_category", "Built-in categories cannot be deleted.")

    if db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == category_id)):
        raise _error(409, "has_children", "This category has sub-categories. Delete or move them first.")
    in_use = db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.category_id == category_id)
    ) or db.scalar(
        select(func.count())
        .select_from(ClassificationRule)
        .where(ClassificationRule.category_id == category_id)
    )
    if in_use:
        raise _error(
            409, "in_use", "This category has transactions or rules. Move them to another category first."
        )
    db.delete(category)
    db.commit()
