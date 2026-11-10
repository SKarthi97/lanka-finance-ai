"""Monthly budgets per category: what was set, what has been spent, what is left.

Spent is the category's debits minus its credits in the month (a refund reduces spending),
never below zero. Only statements that count in analytics and rows that are not repeats count.
All arithmetic is exact Decimal.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Category, Document, Transaction
from app.services.extraction import ACTIVE_STATUSES
from app.tuning import BUDGET_NEAR as NEAR

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


@dataclass
class BudgetLine:
    category_id: int
    category_name: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal  # negative when over
    percent: int  # spent as a whole percent of the limit; for drawing and text only
    state: str  # under | near | over


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)


def _dec(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS)


def spent_by_category(db: Session, user_id: int, year: int, month: int) -> dict[int, Decimal]:
    start, end = month_bounds(year, month)
    included = select(Document.id).where(
        Document.user_id == user_id, Document.status.in_(ACTIVE_STATUSES)
    )
    rows = db.execute(
        select(
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.debit), 0),
            func.coalesce(func.sum(Transaction.credit), 0),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.document_id.in_(included),
            Transaction.is_duplicate.is_(False),
            Transaction.category_id.is_not(None),
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .group_by(Transaction.category_id)
    ).all()
    return {cid: max(_dec(debit) - _dec(credit), ZERO) for cid, debit, credit in rows}


def status(limit: Decimal, spent: Decimal) -> tuple[int, str]:
    percent = int((spent / limit * 100).to_integral_value()) if limit > 0 else 0
    if spent > limit:
        return percent, "over"
    if spent >= limit * NEAR:
        return percent, "near"
    return percent, "under"


def lines(db: Session, user_id: int, year: int, month: int) -> list[BudgetLine]:
    spent = spent_by_category(db, user_id, year, month)
    children: dict[int, list[int]] = {}
    for child_id, parent_id in db.execute(
        select(Category.id, Category.parent_id).where(
            Category.user_id == user_id, Category.parent_id.is_not(None)
        )
    ):
        children.setdefault(parent_id, []).append(child_id)
    out: list[BudgetLine] = []
    for budget, category in db.execute(
        select(Budget, Category)
        .join(Category, Category.id == Budget.category_id)
        .where(Budget.user_id == user_id)
    ).all():
        # A budget on a parent category also counts what its sub-categories spent.
        used = spent.get(category.id, ZERO) + sum(
            (spent.get(child, ZERO) for child in children.get(category.id, [])), ZERO
        )
        percent, state = status(budget.monthly_amount, used)
        out.append(
            BudgetLine(
                category_id=category.id,
                category_name=category.name,
                limit=_dec(budget.monthly_amount),
                spent=used,
                remaining=_dec(budget.monthly_amount) - used,
                percent=percent,
                state=state,
            )
        )
    out.sort(key=lambda b: (-b.percent, b.category_name))
    return out
