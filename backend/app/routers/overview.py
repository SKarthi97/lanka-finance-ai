from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Bank, Category, Document, Transaction, UserSession
from app.services import transfers
from app.services.coverage import account_coverage, covered_months
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api", tags=["overview"])

CENTS = Decimal("0.01")


def _dec(value) -> Decimal:
    """SQLite sums come back as floats in tests; Postgres returns exact Decimals."""
    return Decimal(str(value)).quantize(CENTS)


_covered_months = covered_months  # kept under the old name for existing callers


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


class HistoryPoint(BaseModel):
    year: int
    month: int
    balance: Decimal  # the account's balance at the end of that month


class BalanceOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    account_last4: str | None
    balance: Decimal
    as_of: date
    # Up to 12 month-end balances ending with the account's latest month with transactions.
    history: list[HistoryPoint] = []
    # Latest month's balance minus the month before; None when there is only one month.
    change: Decimal | None = None
    change_year: int | None = None
    change_month: int | None = None


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
    parent_id: int | None = None  # set for a sub-category, so the page can group it under its parent
    parent_name: str | None = None


class BankTotal(BaseModel):
    bank_code: str | None
    bank_name: str | None
    income: Decimal
    expense: Decimal
    net: Decimal
    transactions: int


class CoverageOut(BaseModel):
    gap_months: int  # months with no statement, between an account's first and last statement
    balance_breaks: int  # places where one statement's closing balance is not the next one's opening


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
    month_by_bank: list[BankTotal]  # empty when a single bank is selected
    year_by_bank: list[BankTotal]
    coverage: CoverageOut
    transfer_suggestions: int  # possible own-account transfers waiting for you
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
                parent_id=category.parent_id if category else None,
                parent_name=categories[category.parent_id].name
                if category and category.parent_id in categories
                else None,
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


def _bank_split(
    db: Session, included, start: date, end: date, categories: dict[int, Category]
) -> list[BankTotal]:
    """Income and expense per bank, with the same rules as `_totals` (transfers and repeated
    rows left out; uncategorised counted by direction)."""
    rows = db.execute(
        select(
            Transaction.bank_id,
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.credit), 0),
            func.coalesce(func.sum(Transaction.debit), 0),
            func.count(),
        )
        .where(
            Transaction.document_id.in_(included),
            Transaction.is_duplicate.is_(False),
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )
        .group_by(Transaction.bank_id, Transaction.category_id)
    ).all()
    banks = {b.id: b for b in db.scalars(select(Bank))}

    zero = Decimal("0.00")
    totals: dict[int | None, list] = {}
    for bank_id, category_id, credit, debit, n in rows:
        entry = totals.setdefault(bank_id, [zero, zero, 0])
        entry[2] += n
        category = categories.get(category_id)
        if category is not None and category.kind == "transfer":
            continue
        entry[0] += _dec(credit)
        entry[1] += _dec(debit)

    out = [
        BankTotal(
            bank_code=banks[bank_id].code if bank_id in banks else None,
            bank_name=banks[bank_id].name if bank_id in banks else None,
            income=income,
            expense=expense,
            net=income - expense,
            transactions=count,
        )
        for bank_id, (income, expense, count) in totals.items()
    ]
    out.sort(key=lambda b: b.bank_name or "")
    return out


HISTORY_MONTHS = 12


def _account_history(
    db: Session, included, bank_id: int | None
) -> dict[tuple, list[HistoryPoint]]:
    """Month-end balance per (bank, account): the running balance of its last transaction in
    each month, carried forward through months without transactions."""
    conditions = [Transaction.document_id.in_(included), Transaction.is_duplicate.is_(False)]
    if bank_id is not None:
        conditions.append(Transaction.bank_id == bank_id)
    rows = db.execute(
        select(
            Transaction.bank_id,
            Transaction.account_id,
            Transaction.transaction_date,
            Transaction.running_balance,
        )
        .where(*conditions)
        .order_by(Transaction.transaction_date, Transaction.document_id, Transaction.seq)
    ).all()

    month_end: dict[tuple, dict[tuple[int, int], Decimal]] = {}
    for bank_key, account_key, when, balance in rows:
        month_end.setdefault((bank_key, account_key), {})[(when.year, when.month)] = _dec(balance)

    history: dict[tuple, list[HistoryPoint]] = {}
    for key, months in month_end.items():
        first, last = min(months), max(months)
        points: list[HistoryPoint] = []
        year, month = first
        carried = months[first]
        while (year, month) <= last:
            carried = months.get((year, month), carried)
            points.append(HistoryPoint(year=year, month=month, balance=carried))
            year, month = year + (month == 12), month % 12 + 1
        history[key] = points[-HISTORY_MONTHS:]
    return history


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

    history = _account_history(db, included, bank_id)
    balances = []
    for key, doc in latest.items():
        points = history.get(key, [])
        change = points[-1].balance - points[-2].balance if len(points) >= 2 else None
        balances.append(
            BalanceOut(
                bank_code=doc.bank.code if doc.bank else None,
                bank_name=doc.bank.name if doc.bank else None,
                account_last4=doc.account.account_number_last4 if doc.account else None,
                balance=doc.closing_balance,
                as_of=doc.period_end,
                history=points,
                change=change,
                change_year=points[-1].year if change is not None else None,
                change_month=points[-1].month if change is not None else None,
            )
        )
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
    month_by_bank = (
        [] if bank_id is not None else _bank_split(db, included, month_start, month_end, categories)
    )
    year_by_bank = (
        []
        if bank_id is not None
        else _bank_split(db, included, date(year, 1, 1), date(year + 1, 1, 1), categories)
    )
    report = list(account_coverage(db, session.user_id).values())

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
        month_by_bank=month_by_bank,
        year_by_bank=year_by_bank,
        coverage=CoverageOut(
            gap_months=sum(len(c.gap_months) for c in report),
            balance_breaks=sum(len(c.breaks) for c in report),
        ),
        transfer_suggestions=len(transfers.find_pairs(db, session.user_id)),
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
