from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import (
    Category,
    ClassificationRule,
    UserSession,
)
from app.routers.categories import _category_or_404, _error  # noqa: F401
from app.services import categorizer

router = APIRouter(prefix="/api", tags=["rules"])


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
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    direction: str | None = None


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=128)
    pattern_type: Literal["contains", "word"] = "contains"
    category_id: int
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    direction: Literal["in", "out"] | None = None


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
        min_amount=rule.min_amount,
        max_amount=rule.max_amount,
        direction=rule.direction,
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
    if body.min_amount is not None and body.max_amount is not None and body.min_amount > body.max_amount:
        raise _error(422, "amount_range", "The smallest amount is more than the largest.")
    rule = ClassificationRule(
        user_id=session.user_id,
        pattern=pattern,
        pattern_type=body.pattern_type,
        min_amount=body.min_amount,
        max_amount=body.max_amount,
        direction=body.direction,
        conditions_key=f"{body.direction or ''}|{body.min_amount if body.min_amount is not None else ''}|{body.max_amount if body.max_amount is not None else ''}",
        category_id=category.id,
        origin="user",
        priority=40,  # above built-in rules, below corrections
    )
    db.add(rule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _error(409, "duplicate_rule", "That rule already exists.") from None

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
