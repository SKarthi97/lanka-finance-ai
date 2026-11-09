from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Bank, Category, Document, Transaction, UserSession
from app.services import interest
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api/savings", tags=["savings"])

INTEREST_CATEGORY = "Interest income"
TAX_CATEGORY = "Tax"
TAX_WORDS = ("INTEREST", "WHT", "WITHHELD")


class InterestMonth(BaseModel):
    month: int
    interest: Decimal  # credited in this month, after tax; shown even when no rate can be worked out
    tax: Decimal  # tax withheld on it, when a line for it was found
    average_balance: Decimal | None  # average end-of-day balance over the days the interest covers
    days: int
    annual_rate: Decimal | None  # percent a year; None when there is too little data behind it
    monthly_rate: Decimal | None  # annual / 12
    assumed: str | None  # what the start of the period was assumed to be, when it had to be
    unrated: int  # credits in the month that could not be rated


class InterestOut(BaseModel):
    year: int
    accounts: int  # accounts that were credited interest in the data
    unrecognised: int  # credits that mention interest but are not in the Interest income category
    months: list[InterestMonth]


@router.get("/interest", response_model=InterestOut)
def interest_by_month(
    year: int = Query(ge=2000, le=2100),
    bank_code: str | None = Query(default=None, max_length=32),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> InterestOut:
    """The interest credited each month and the annual rate it works out to, from the days your
    money was kept. Interest credited in a month pays for the days before it (see services/interest)."""
    included = select(Document.id).where(
        Document.user_id == session.user_id, Document.status.in_(ACTIVE_STATUSES)
    )
    where = [Transaction.document_id.in_(included), Transaction.is_duplicate.is_(False)]
    if bank_code:
        bank = db.scalar(select(Bank).where(Bank.code == bank_code))
        where.append(Transaction.bank_id == (bank.id if bank else -1))

    rows = db.execute(
        select(
            Transaction.bank_id,
            Transaction.account_id,
            Transaction.transaction_date,
            Transaction.running_balance,
            Transaction.credit,
            Transaction.debit,
            Transaction.original_description,
            Category.name,
        )
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*where)
        .order_by(Transaction.transaction_date, Transaction.document_id, Transaction.seq)
    ).all()

    accounts: dict[tuple, interest.Account] = defaultdict(interest.Account)
    key_of: dict[int, tuple] = {}
    unrecognised = 0
    for bank_id, account_id, when, balance, credit, debit, description, category in rows:
        key = (bank_id, account_id)
        account = accounts[key]
        if account_id is not None:
            key_of[account_id] = key
        # rows arrive in order, so the last row of a day sets that day's closing balance
        if account.points and account.points[-1][0] == when:
            account.points[-1] = (when, Decimal(balance))
        else:
            account.points.append((when, Decimal(balance)))
        if category == INTEREST_CATEGORY and Decimal(credit) > 0:
            account.credits.append((when, Decimal(credit)))
        elif category == TAX_CATEGORY and Decimal(debit) > 0 and any(w in description.upper() for w in TAX_WORDS):
            account.taxes.append((when, Decimal(debit)))
        elif Decimal(credit) > 0 and "INTEREST" in description.upper() and when.year == year:
            unrecognised += 1

    # A statement's opening balance is the balance at the end of the day before it starts, so it
    # lets the first days of an account's data count even before its first row.
    for first_day, opening, account_id in db.execute(
        select(Document.period_start, Document.opening_balance, Document.account_id).where(
            Document.id.in_(included), Document.period_start.is_not(None), Document.opening_balance.is_not(None)
        )
    ):
        key = key_of.get(account_id)
        if key is not None:
            before = first_day - timedelta(days=1)
            if all(day != before for day, _ in accounts[key].points):
                accounts[key].points.append((before, Decimal(opening)))
    for account in accounts.values():
        account.points.sort(key=lambda p: p[0])

    paying = [a for a in accounts.values() if a.credits]
    months = interest.monthly_rates(paying, year)
    return InterestOut(
        year=year,
        accounts=len(paying),
        unrecognised=unrecognised,
        months=[
            InterestMonth(
                month=m.month,
                interest=m.interest,
                tax=m.tax,
                average_balance=m.average_balance.quantize(Decimal("0.01")) if m.average_balance is not None else None,
                days=m.days,
                annual_rate=m.annual_rate,
                monthly_rate=m.monthly_rate,
                assumed=m.assumed,
                unrated=m.unrated,
            )
            for m in months
        ],
    )
