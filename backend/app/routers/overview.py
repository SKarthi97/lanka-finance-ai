from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Bank, Category, Document, Transaction, UserSession
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api", tags=["overview"])

CENTS = Decimal("0.01")


def _dec(value) -> Decimal:
    """SQLite sums come back as floats in tests; Postgres returns exact Decimals."""
    return Decimal(str(value)).quantize(CENTS)


def _covered_months(period_start: date | None, period_end: date) -> set[tuple[int, int]]:
    """(year, month) pairs a statement counts for.

    The month its period ends in, plus every month that lies wholly inside the period.
    A monthly statement 31 Oct - 30 Nov therefore counts for November only, so a missing
    October statement stays visible; a multi-year statement counts for every month it spans.
    """
    covered = {(period_end.year, period_end.month)}
    if period_start is None:
        return covered

    year, month = period_start.year, period_start.month
    for _ in range(1200):  # 100 years of months; guards against bad data
        first = date(year, month, 1)
        next_first = date(year + (month == 12), month % 12 + 1, 1)
        if next_first - timedelta(days=1) > period_end:
            break
        if first > period_start:
            covered.add((year, month))
        year, month = next_first.year, next_first.month
    return covered


def _transaction_years(db: Session, user_id: int, statuses: tuple[str, ...]) -> set[int]:
    """Years in which the user has transactions from statements with these statuses."""
    year_of = extract("year", Transaction.transaction_date)
    return {
        int(y)
        for (y,) in db.execute(
            select(year_of)
            .join(Document, Document.id == Transaction.document_id)
            .where(
                Document.user_id == user_id,
                Document.status.in_(statuses),
                Transaction.is_duplicate.is_(False),
            )
            .distinct()
        )
    }


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
    income: Decimal  # credits that are not transfers
    expense: Decimal  # debits that are not transfers
    net: Decimal
    transfers_in: Decimal  # credits in categories of kind "transfer"
    transfers_out: Decimal
    transactions: int
    uncategorised: int  # counted by direction until you categorise them


class CategoryTotal(BaseModel):
    category_id: int | None  # None = uncategorised
    name: str
    kind: str | None
    income: Decimal
    expense: Decimal
    transactions: int


class TopExpense(BaseModel):
    id: int
    transaction_date: date
    description: str
    amount: Decimal
    category_name: str | None
    bank_code: str | None


class DashboardOut(BaseModel):
    balances: list[BalanceOut]
    total_balance: Decimal
    as_of: date | None
    month: Totals
    previous_month: Totals  # the month before, for the comparison line
    year: Totals
    top_expenses: list[TopExpense]  # largest expenses of the month, transfers excluded
    uncategorised_total: int  # every uncategorised transaction, any period
    ai_unsure: int  # AI suggestions below the confidence threshold, waiting for you
    month_by_category: list[CategoryTotal]
    year_by_category: list[CategoryTotal]
    needs_review: int
    has_data: bool
    years: list[int]  # every year with transactions, for the period selector
    banks: list[BankOut]  # banks that have statements, for the bank filter


def _totals(
    db: Session,
    included,
    start: date,
    end: date,
    categories: dict[int, Category],
    bank_id: int | None = None,
) -> tuple[Totals, list[CategoryTotal]]:
    """Income and expense exclude transfers between your own accounts.

    Uncategorised transactions are counted by direction (a credit is income, a debit is
    expense) so the totals do not change meaning while categorising is unfinished.
    A repeated transaction from an overlapping statement counts once.
    """
    conditions = [
        Transaction.document_id.in_(included),
        Transaction.is_duplicate.is_(False),
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    ]
    if bank_id is not None:
        conditions.append(Transaction.bank_id == bank_id)
    rows = db.execute(
        select(
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.credit), 0),
            func.coalesce(func.sum(Transaction.debit), 0),
            func.count(),
        )
        .where(*conditions)
        .group_by(Transaction.category_id)
    ).all()

    zero = Decimal("0.00")
    income = expense = transfers_in = transfers_out = zero
    count = uncategorised = 0
    by_category: list[CategoryTotal] = []

    for category_id, credit, debit, n in rows:
        credit, debit = _dec(credit), _dec(debit)
        category = categories.get(category_id)
        count += n
        if category is None:
            uncategorised += n
        if category is not None and category.kind == "transfer":
            transfers_in += credit
            transfers_out += debit
        else:
            income += credit
            expense += debit
        by_category.append(
            CategoryTotal(
                category_id=category_id,
                name=category.name if category else "Uncategorised",
                kind=category.kind if category else None,
                income=credit,
                expense=debit,
                transactions=n,
            )
        )

    by_category.sort(key=lambda c: (-max(c.expense, c.income), c.name))
    totals = Totals(
        income=income,
        expense=expense,
        net=income - expense,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        transactions=count,
        uncategorised=uncategorised,
    )
    return totals, by_category


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
    bank_code: str | None = Query(default=None, max_length=32),
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
    bank = db.scalar(select(Bank).where(Bank.code == bank_code)) if bank_code else None
    bank_id = (bank.id if bank else -1) if bank_code else None  # unknown bank: nothing
    all_banks = sorted(
        {d.bank.code: d.bank for d in statements if d.bank}.values(), key=lambda b: b.name
    )
    latest: dict[tuple, Document] = {}
    for doc in statements:
        if bank_id is not None and doc.bank_id != bank_id:
            continue
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
    categories = {
        c.id: c for c in db.scalars(select(Category).where(Category.user_id == session.user_id))
    }
    month_totals, month_by_category = _totals(
        db, included, month_start, month_end, categories, bank_id
    )
    previous_totals, _ = _totals(
        db, included, _add_months(month_start, -1), month_start, categories, bank_id
    )
    year_totals, year_by_category = _totals(
        db, included, date(year, 1, 1), date(year + 1, 1, 1), categories, bank_id
    )
    top_expenses = _top_expenses(db, included, month_start, month_end, categories, bank_id)

    needs_review = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.user_id == session.user_id, Document.status == "needs_review")
    )

    counted = [Transaction.document_id.in_(included), Transaction.is_duplicate.is_(False)]
    uncategorised_total = db.scalar(
        select(func.count()).select_from(Transaction).where(*counted, Transaction.category_id.is_(None))
    )
    ai_unsure = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(*counted, Transaction.classification_source == "llm_unsure")
    )

    return DashboardOut(
        balances=balances,
        total_balance=sum((b.balance for b in balances), Decimal("0.00")),
        as_of=max((b.as_of for b in balances), default=None),
        month=month_totals,
        previous_month=previous_totals,
        top_expenses=top_expenses,
        uncategorised_total=uncategorised_total or 0,
        ai_unsure=ai_unsure or 0,
        banks=[BankOut(code=b.code, name=b.name) for b in all_banks],
        year=year_totals,
        month_by_category=month_by_category,
        year_by_category=year_by_category,
        needs_review=needs_review or 0,
        has_data=bool(statements),
        years=sorted(_transaction_years(db, session.user_id, ACTIVE_STATUSES) | {year}),
    )


def _add_months(first_of_month: date, delta: int) -> date:
    index = first_of_month.year * 12 + (first_of_month.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def _month_range(first: date, count: int) -> list[tuple[int, int]]:
    spans = [_add_months(first, i) for i in range(count)]
    return [(d.year, d.month) for d in spans]


def _top_expenses(
    db: Session,
    included,
    start: date,
    end: date,
    categories: dict[int, Category],
    bank_id: int | None,
    limit: int = 5,
) -> list[TopExpense]:
    transfer_ids = [cid for cid, c in categories.items() if c.kind == "transfer"]
    conditions = [
        Transaction.document_id.in_(included),
        Transaction.is_duplicate.is_(False),
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
        Transaction.debit > 0,
    ]
    if transfer_ids:
        conditions.append(
            Transaction.category_id.is_(None) | Transaction.category_id.not_in(transfer_ids)
        )
    if bank_id is not None:
        conditions.append(Transaction.bank_id == bank_id)
    rows = db.execute(
        select(Transaction, Bank.code)
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .where(*conditions)
        .order_by(Transaction.debit.desc(), Transaction.id)
        .limit(limit)
    ).all()
    return [
        TopExpense(
            id=t.id,
            transaction_date=t.transaction_date,
            description=t.original_description,
            amount=_dec(t.debit),
            category_name=categories[t.category_id].name if t.category_id in categories else None,
            bank_code=code,
        )
        for t, code in rows
    ]


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

    A statement counts for the month its period ends in and for every month wholly inside
    its period (see `_covered_months`), so a 31 Oct - 30 Nov statement is the November
    statement while a multi-year statement fills every month it spans. A cell is `ok` for
    reconciled/accepted and `review` for a statement still needing review. Missing months
    have no cell.
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

    covered = {d.id: _covered_months(d.period_start, d.period_end) for d in docs}
    years = sorted(
        {y for months in covered.values() for y, _ in months}
        | _transaction_years(db, session.user_id, ACTIVE_STATUSES + ("needs_review",))
        | {year}
    )
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
        status = "ok" if doc.status in ACTIVE_STATUSES else "review"
        for cell_year, cell_month in covered[doc.id]:
            if cell_year != year:
                continue
            existing = row.cells.get(cell_month)
            # A clean statement beats one needing review; otherwise the latest wins.
            if existing is None or existing.status == "review" or status == "ok":
                row.cells[cell_month] = TrackerCell(status=status, document_id=doc.id)

    ordered = sorted(rows.values(), key=lambda r: (r.bank_name or "", r.account_last4 or ""))
    return TrackerOut(year=year, years=years, rows=ordered)
