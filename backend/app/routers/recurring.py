from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import merchants, recurring

router = APIRouter(prefix="/api", tags=["recurring"])

ZERO = Decimal("0.00")


class RecurringOut(BaseModel):
    stem: str  # the repeated part of the description
    name: str  # the clean merchant name for it
    direction: str  # expense | income
    cadence: str  # weekly | fortnightly | monthly | quarterly | yearly
    count: int
    typical_amount: Decimal
    last_date: date
    next_expected: date
    state: str  # upcoming | due | overdue | ended
    category_name: str | None
    monthly_equivalent: Decimal


class RecurringListOut(BaseModel):
    items: list[RecurringOut]
    monthly_expense: Decimal  # what the active ones cost per month
    monthly_income: Decimal


@router.get("/recurring", response_model=RecurringListOut)
def list_recurring(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> RecurringListOut:
    found = recurring.find(db, session.user_id)
    named = merchants.names_for(db, session.user_id, [r.stem for r in found])
    active = [r for r in found if r.state != "ended"]
    return RecurringListOut(
        items=[RecurringOut(**vars(r), name=named[r.stem][0]) for r in found],
        monthly_expense=sum((r.monthly_equivalent for r in active if r.direction == "expense"), ZERO),
        monthly_income=sum((r.monthly_equivalent for r in active if r.direction == "income"), ZERO),
    )
