from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Budget, Category, UserSession
from app.services import budgets

router = APIRouter(prefix="/api/budgets", tags=["budgets"])

ZERO = Decimal("0.00")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class BudgetOut(BaseModel):
    category_id: int
    category_name: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal  # negative when over the limit
    percent: int
    state: str  # under | near | over


class BudgetsOut(BaseModel):
    year: int
    month: int
    items: list[BudgetOut]
    total_limit: Decimal
    total_spent: Decimal
    over: int  # how many budgets are over their limit


class BudgetIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


@router.get("", response_model=BudgetsOut)
def list_budgets(
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> BudgetsOut:
    today = date.today()
    year, month = year or today.year, month or today.month
    items = budgets.lines(db, session.user_id, year, month)
    return BudgetsOut(
        year=year,
        month=month,
        items=[BudgetOut(**vars(b)) for b in items],
        total_limit=sum((b.limit for b in items), ZERO),
        total_spent=sum((b.spent for b in items), ZERO),
        over=sum(1 for b in items if b.state == "over"),
    )


@router.put("/{category_id}", response_model=BudgetIn)
def set_budget(
    category_id: int,
    body: BudgetIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> BudgetIn:
    """Create or change the monthly limit for an expense category."""
    category = db.get(Category, category_id)
    if category is None or category.user_id != session.user_id:
        raise _error(404, "category_not_found", "Category not found.")
    if category.kind != "expense":
        raise _error(422, "not_an_expense_category", "Budgets are for expense categories.")
    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == session.user_id, Budget.category_id == category_id
        )
    )
    if budget is None:
        db.add(Budget(user_id=session.user_id, category_id=category_id, monthly_amount=body.amount))
    else:
        budget.monthly_amount = body.amount
    db.commit()
    return body


@router.delete("/{category_id}", status_code=204)
def delete_budget(
    category_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == session.user_id, Budget.category_id == category_id
        )
    )
    if budget is None:
        raise _error(404, "not_found", "No budget for this category.")
    db.delete(budget)
    db.commit()
