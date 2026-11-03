from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import (
    Category,
    ClassificationRule,
    Job,
    Transaction,
    UserSession,
)
from app.services import categorizer
from app.services.llm_classifier import JOB_TYPE, enqueue_classification

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


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["income", "expense", "transfer"]


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
    return [
        CategoryOut(
            id=c.id, name=c.name, kind=c.kind, is_system=c.is_system, transactions=counts.get(c.id, 0)
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
    category = Category(user_id=session.user_id, name=body.name.strip(), kind=body.kind)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(409, "duplicate_category", "A category with that name already exists.")
    return CategoryOut(
        id=category.id, name=category.name, kind=category.kind, is_system=False, transactions=0
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


# --- rules ------------------------------------------------------------------------------------


class RuleOut(BaseModel):
    id: int
    pattern: str
    pattern_type: str
    category_id: int
    category_name: str
    origin: str
    priority: int
    enabled: bool
    hit_count: int


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=128)
    pattern_type: Literal["contains", "word"] = "contains"
    category_id: int


class RulePatch(BaseModel):
    enabled: bool


class RuleChanged(RuleOut):
    changed: int  # transactions re-categorised by this change


def _rule_out(rule: ClassificationRule, category_name: str) -> RuleOut:
    return RuleOut(
        id=rule.id,
        pattern=rule.pattern,
        pattern_type=rule.pattern_type,
        category_id=rule.category_id,
        category_name=category_name,
        origin=rule.origin,
        priority=rule.priority,
        enabled=rule.enabled,
        hit_count=rule.hit_count,
    )


@router.get("/rules", response_model=list[RuleOut])
def list_rules(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> list[RuleOut]:
    categorizer.ensure_defaults(db, session.user_id)
    db.commit()
    rows = db.execute(
        select(ClassificationRule, Category.name)
        .join(Category, Category.id == ClassificationRule.category_id)
        .where(ClassificationRule.user_id == session.user_id)
        .order_by(
            ClassificationRule.origin == "system",  # your rules first
            ClassificationRule.priority.desc(),
            ClassificationRule.pattern,
        )
    ).all()
    return [_rule_out(rule, name) for rule, name in rows]


@router.post("/rules", response_model=RuleChanged, status_code=201)
def create_rule(
    body: RuleIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> RuleChanged:
    category = _category_or_404(db, session.user_id, body.category_id)
    pattern = categorizer.normalise(body.pattern)
    rule = ClassificationRule(
        user_id=session.user_id,
        pattern=pattern,
        pattern_type=body.pattern_type,
        category_id=category.id,
        origin="user",
        priority=40,  # above built-in rules, below corrections
    )
    db.add(rule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _error(409, "duplicate_rule", "That rule already exists.")

    changed = categorizer.classify_rows(db, session.user_id, sources=categorizer.OVERRIDE_AI)
    db.commit()
    return RuleChanged(**_rule_out(rule, category.name).model_dump(), changed=changed)


@router.patch("/rules/{rule_id}", response_model=RuleChanged)
def update_rule(
    rule_id: int,
    body: RulePatch,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> RuleChanged:
    rule = db.get(ClassificationRule, rule_id)
    if rule is None or rule.user_id != session.user_id:
        raise _error(404, "rule_not_found", "Rule not found.")
    rule.enabled = body.enabled
    db.flush()
    changed = categorizer.classify_rows(db, session.user_id)
    db.commit()
    return RuleChanged(
        **_rule_out(rule, db.get(Category, rule.category_id).name).model_dump(), changed=changed
    )


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    rule = db.get(ClassificationRule, rule_id)
    if rule is None or rule.user_id != session.user_id:
        raise _error(404, "rule_not_found", "Rule not found.")
    if rule.origin == "system":
        raise _error(409, "system_rule", "Built-in rules cannot be deleted. Turn them off instead.")
    db.delete(rule)
    db.flush()
    categorizer.classify_rows(db, session.user_id)
    db.commit()


# --- correcting one transaction ------------------------------------------------------------------


class CorrectionIn(BaseModel):
    category_id: int | None
    # Also learn a rule from this transaction and apply it to similar ones.
    create_rule: bool = False


class CorrectionOut(BaseModel):
    transaction_id: int
    category_id: int | None
    category_name: str | None
    stem: str
    similar_count: int  # other transactions the same rule would cover
    rule_id: int | None
    changed: int  # other transactions re-categorised


@router.put("/transactions/{transaction_id}/category", response_model=CorrectionOut)
def correct_transaction(
    transaction_id: int,
    body: CorrectionIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> CorrectionOut:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != session.user_id:
        raise _error(404, "not_found", "Transaction not found.")

    category = None
    if body.category_id is not None:
        category = _category_or_404(db, session.user_id, body.category_id)
    if body.create_rule and category is None:
        raise _error(422, "category_required", "Choose a category to create a rule.")

    categorizer.set_manual_category(db, session.user_id, transaction, body.category_id)
    stem = categorizer.description_stem(transaction.original_description)

    rule_id, changed = None, 0
    if body.create_rule and category is not None:
        db.flush()
        rule, changed = categorizer.apply_stem(db, session.user_id, stem, category.id)
        rule_id = rule.id

    similar = categorizer.count_similar(db, session.user_id, stem, exclude_id=transaction.id)
    db.commit()
    return CorrectionOut(
        transaction_id=transaction.id,
        category_id=body.category_id,
        category_name=category.name if category else None,
        stem=stem,
        similar_count=0 if body.create_rule else similar,
        rule_id=rule_id,
        changed=changed,
    )


# --- review queue and the AI pass ------------------------------------------------------------------


class ReviewGroup(BaseModel):
    stem: str
    count: int
    example: str


class ReviewOut(BaseModel):
    total: int
    groups: list[ReviewGroup]


class ApplyIn(BaseModel):
    stem: str = Field(min_length=2, max_length=128)
    category_id: int


class ApplyOut(BaseModel):
    rule_id: int
    changed: int


class StatusOut(BaseModel):
    ai_enabled: bool
    ai_pending: bool
    uncategorised: int


@router.get("/categorization/review", response_model=ReviewOut)
def review_queue(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> ReviewOut:
    categorizer.ensure_defaults(db, session.user_id)
    db.commit()
    groups, total = categorizer.review_groups(db, session.user_id)
    return ReviewOut(total=total, groups=[ReviewGroup(**g) for g in groups])


@router.post("/categorization/apply", response_model=ApplyOut)
def apply_to_group(
    body: ApplyIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApplyOut:
    """Give every transaction matching this description one category, and remember it."""
    category = _category_or_404(db, session.user_id, body.category_id)
    rule, changed = categorizer.apply_stem(
        db, session.user_id, categorizer.normalise(body.stem), category.id
    )
    db.commit()
    return ApplyOut(rule_id=rule.id, changed=changed)


@router.post("/categorization/reclassify")
def reclassify(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> dict:
    changed = categorizer.classify_rows(db, session.user_id)
    db.commit()
    return {"changed": changed}


@router.get("/categorization/status", response_model=StatusOut)
def status(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StatusOut:
    pending = db.scalars(
        select(Job).where(Job.type == JOB_TYPE, Job.status.in_(("queued", "running")))
    ).all()
    uncategorised = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.user_id == session.user_id,
            Transaction.is_duplicate.is_(False),
            Transaction.category_id.is_(None),
            or_(
                Transaction.classification_source.is_(None),
                Transaction.classification_source == "llm_unsure",
            ),
        )
    )
    return StatusOut(
        ai_enabled=settings.llm_classify_enabled,
        ai_pending=any((j.payload or {}).get("user_id") == session.user_id for j in pending),
        uncategorised=uncategorised or 0,
    )


@router.post("/categorization/ai", status_code=202)
def ask_ai(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Queue the local model to suggest categories for what the rules left over."""
    if not settings.llm_classify_enabled:
        raise _error(409, "ai_disabled", "AI categorisation is turned off.")
    # Rows the model judged unsure get another chance after you ask again.
    db.execute(
        Transaction.__table__.update()
        .where(
            Transaction.user_id == session.user_id,
            Transaction.classification_source == "llm_unsure",
        )
        .values(classification_source=None)
    )
    queued = enqueue_classification(db, settings, session.user_id)
    db.commit()
    return {"queued": queued}
