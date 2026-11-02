from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Bank, Document, Transaction, UserSession
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api", tags=["overview"])

CENTS = Decimal("0.01")


def _dec(value) -> Decimal:
    """SQLite sums come back as floats in tests; Postgres returns exact Decimals."""
    return Decimal(str(value)).quantize(CENTS)


# --- banks ---------------------------------------------------------------------


class BankOut(BaseModel):
    code: str
    name: str


@router.get("/banks", response_model=list[BankOut])
def list_banks(
    _: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> list[BankOut]:
    return [
        BankOut(code=b.code, name=b.name)
        for b in db.scalars(select(Bank).order_by(Bank.name))
    ]


# --- dashboard -----------------------------------------------------------------


class BalanceOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    account_last4: str | None
    balance: Decimal
    as_of: date


class Totals(BaseModel):
    income: Decimal  # credits
    expense: Decimal  # debits
    net: Decimal
    transactions: int


class DashboardOut(BaseModel):
    balances: list[BalanceOut]
    total_balance: Decimal
    as_of: date | None
    month: Totals
    year: Totals
    needs_review: int
    has_data: bool


def _totals(db: Session, included, start: date, end: date) -> Totals:
    credit, debit, count = db.execute(
        select(
            func.coalesce(func.sum(Transaction.credit), 0),
            func.coalesce(func.sum(Transaction.debit), 0),
            func.count(),
        ).where(
            Transaction.document_id.in_(included),
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
    ).one()
    income, expense = _dec(credit), _dec(debit)
    return Totals(income=income, expense=expense, net=income - expense, transactions=count)


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> DashboardOut:
    """Current balances plus income/expense for a month and its year.

    The browser passes its own year and month so the server's timezone never decides
    which month is "this month". Only reconciled or accepted statements count;
    statements needing review are excluded (docs/00-architecture.md section 8.6).
    Income and expense are credits and debits: until categorisation exists (Phase 4)
    they include transfers and loan movements.
    """
    today = date.today()
    year = year or today.year
    month = month or today.month

    included = select(Document.id).where(
        Document.user_id == session.user_id, Document.status.in_(ACTIVE_STATUSES)
    )

    # Current balance per bank/account = closing balance of its latest statement.
    statements = db.scalars(
        select(Document)
        .where(
            Document.user_id == session.user_id,
            Document.status.in_(ACTIVE_STATUSES),
            Document.closing_balance.is_not(None),
            Document.period_end.is_not(None),
        )
        .order_by(Document.period_end, Document.id)
    ).all()
    latest: dict[tuple, Document] = {}
    for doc in statements:
        latest[(doc.bank_id, doc.account_id)] = doc

    balances = [
        BalanceOut(
            bank_code=doc.bank.code if doc.bank else None,
            bank_name=doc.bank.name if doc.bank else None,
            account_last4=doc.account.account_number_last4 if doc.account else None,
            balance=doc.closing_balance,
            as_of=doc.period_end,
        )
        for doc in latest.values()
    ]
    balances.sort(key=lambda b: (b.bank_name or "", b.account_last4 or ""))

    month_start = date(year, month, 1)
    month_end = date(year + (month == 12), month % 12 + 1, 1)

    needs_review = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.user_id == session.user_id, Document.status == "needs_review")
    )

    return DashboardOut(
        balances=balances,
        total_balance=sum((b.balance for b in balances), Decimal("0.00")),
        as_of=max((b.as_of for b in balances), default=None),
        month=_totals(db, included, month_start, month_end),
        year=_totals(db, included, date(year, 1, 1), date(year + 1, 1, 1)),
        needs_review=needs_review or 0,
        has_data=bool(statements),
    )


# --- statement tracker ---------------------------------------------------------


class TrackerCell(BaseModel):
    status: str  # ok | review
    document_id: int


class TrackerRow(BaseModel):
    bank_code: str | None
    bank_name: str | None
    account_last4: str | None
    cells: dict[int, TrackerCell]  # month number -> cell


class TrackerOut(BaseModel):
    year: int
    years: list[int]
    rows: list[TrackerRow]


@router.get("/tracker", response_model=TrackerOut)
def tracker(
    year: int = Query(default=None, ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> TrackerOut:
    """Which months have a statement, per bank and account.

    A statement belongs to the month its period ends in (a 31 Oct - 30 Nov statement is
    the November statement). A cell is `ok` for reconciled/accepted and `review` for a
    statement still needing review. Missing months have no cell.
    """
    year = year or date.today().year

    docs = db.scalars(
        select(Document)
        .where(
            Document.user_id == session.user_id,
            Document.period_end.is_not(None),
            Document.status.in_(ACTIVE_STATUSES + ("needs_review",)),
        )
        .order_by(Document.period_end, Document.id)
    ).all()

    years = sorted({d.period_end.year for d in docs} | {year})
    rows: dict[tuple, TrackerRow] = {}

    for doc in docs:
        key = (doc.bank_id, doc.account_id)
        row = rows.setdefault(
            key,
            TrackerRow(
                bank_code=doc.bank.code if doc.bank else None,
                bank_name=doc.bank.name if doc.bank else None,
                account_last4=doc.account.account_number_last4 if doc.account else None,
                cells={},
            ),
        )
        if doc.period_end.year != year:
            continue
        status = "ok" if doc.status in ACTIVE_STATUSES else "review"
        existing = row.cells.get(doc.period_end.month)
        # A clean statement beats one needing review; otherwise the latest wins.
        if existing is None or existing.status == "review" or status == "ok":
            row.cells[doc.period_end.month] = TrackerCell(status=status, document_id=doc.id)

    ordered = sorted(rows.values(), key=lambda r: (r.bank_name or "", r.account_last4 or ""))
    return TrackerOut(year=year, years=years, rows=ordered)
