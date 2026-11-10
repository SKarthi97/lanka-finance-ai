"""Income, expense and balance month by month (GET /api/dashboard/trend)."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Bank, Category, Document, Transaction, UserSession
from app.routers.overview import _add_months, _dec, _month_range
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api", tags=["overview"])


# --- trend ---------------------------------------------------------------------


class TrendMonth(BaseModel):
    year: int
    month: int
    income: Decimal
    expense: Decimal
    net: Decimal
    balance: Decimal | None  # total across accounts at month end; None after the last data


class TrendOut(BaseModel):
    months: list[TrendMonth]


@router.get("/dashboard/trend", response_model=TrendOut)
def trend(
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
    months: int = Query(default=12, ge=2, le=60),
    bank_code: str | None = Query(default=None, max_length=32),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> TrendOut:
    """Income, expense and total balance for `months` months ending at year/month.

    Income and expense leave out transfers, like the dashboard. The balance at a month's end
    is, per account, the running balance of its last transaction up to that day, summed.
    """
    today = date.today()
    last = date(year or today.year, month or today.month, 1)
    first = _add_months(last, -(months - 1))
    after = _add_months(last, 1)

    included = select(Document.id).where(
        Document.user_id == session.user_id, Document.status.in_(ACTIVE_STATUSES)
    )
    bank = db.scalar(select(Bank).where(Bank.code == bank_code)) if bank_code else None
    base = [Transaction.document_id.in_(included), Transaction.is_duplicate.is_(False)]
    if bank_code:
        base.append(Transaction.bank_id == (bank.id if bank else -1))  # unknown bank: nothing

    window = _month_range(first, months)
    income = {key: Decimal("0.00") for key in window}
    expense = {key: Decimal("0.00") for key in window}
    year_of = extract("year", Transaction.transaction_date)
    month_of = extract("month", Transaction.transaction_date)
    for y, m, kind, credit, debit in db.execute(
        select(
            year_of,
            month_of,
            Category.kind,
            func.coalesce(func.sum(Transaction.credit), 0),
            func.coalesce(func.sum(Transaction.debit), 0),
        )
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*base, Transaction.transaction_date >= first, Transaction.transaction_date < after)
        .group_by(year_of, month_of, Category.kind)
    ):
        if kind == "transfer":
            continue
        key = (int(y), int(m))
        income[key] += _dec(credit)
        expense[key] += _dec(debit)

    # Month-end balances: walk the rows in order, remembering each account's latest balance.
    rows = db.execute(
        select(
            Transaction.bank_id,
            Transaction.account_id,
            Transaction.transaction_date,
            Transaction.running_balance,
        )
        .where(*base, Transaction.transaction_date < after)
        .order_by(Transaction.transaction_date, Transaction.document_id, Transaction.seq)
    ).all()
    latest_date = rows[-1][2] if rows else None
    month_end: dict[tuple[int, int], dict[tuple, Decimal]] = {}
    current: dict[tuple, Decimal] = {}
    for bank_key, account_key, when, balance in rows:
        current[(bank_key, account_key)] = _dec(balance)
        month_end[(when.year, when.month)] = dict(current)

    # Balances carry forward from months before the window.
    earlier = sorted(k for k in month_end if k < (first.year, first.month))
    carried: dict[tuple, Decimal] = month_end[earlier[-1]] if earlier else {}

    out: list[TrendMonth] = []
    for y, m in window:
        if (y, m) in month_end:
            carried = month_end[(y, m)]
        beyond = latest_date is None or (y, m) > (latest_date.year, latest_date.month)
        balance = None if (beyond or not carried) else sum(carried.values(), Decimal("0.00"))
        out.append(
            TrendMonth(
                year=y,
                month=m,
                income=income[(y, m)],
                expense=expense[(y, m)],
                net=income[(y, m)] - expense[(y, m)],
                balance=balance,
            )
        )
    return TrendOut(months=out)
