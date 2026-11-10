"""Savings insights from the statements: what each bank pays, where the rate is falling, money that
may be sitting idle, and where the balance is heading.

Everything is arithmetic on the statement figures (see services/interest.py for how a rate is worked
out). Nothing here is a forecast of the market or advice: the projection just continues the recent
change in your balance in a straight line, and says so.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bank, Category, Document, Transaction
from app.services import interest
from app.services.extraction import ACTIVE_STATUSES

INTEREST_CATEGORY = "Interest income"
TAX_CATEGORY = "Tax"
TAX_WORDS = ("INTEREST", "WHT", "WITHHELD", "AIT", "ADVANCE INCOME")

TRAILING_DAYS = 365  # the window for "what a bank pays"
DROP_POINTS = Decimal("0.50")  # percentage points: a fall at least this big is worth telling
DROP_BASELINE = 3  # the latest credit is compared with the average of up to this many before it
DROP_MIN_BEFORE = 2
IDLE_NO_INTEREST_DAYS = 180
IDLE_WINDOW_DAYS = 90
IDLE_MIN_BALANCE = Decimal("25000")
PROJECTION_MONTHS = 12
TREND_MONTHS = 6


@dataclass
class AccountInfo:
    bank_code: str | None
    bank_name: str | None
    last4: str | None
    data: interest.Account
    last_covered: date | None = None  # where the account's newest statement ends



def load_accounts(
    db: Session, user_id: int, bank_code: str | None = None, year: int | None = None
) -> tuple[list[AccountInfo], int]:
    """Every account's end-of-day balances, interest credits and tax lines, plus how many credits in
    `year` mention interest but are not in the Interest income category."""
    included = select(Document.id).where(Document.user_id == user_id, Document.status.in_(ACTIVE_STATUSES))
    where = [Transaction.user_id == user_id, Transaction.document_id.in_(included), Transaction.is_duplicate.is_(False)]
    if bank_code:
        bank = db.scalar(select(Bank).where(Bank.code == bank_code))
        where.append(Transaction.bank_id == (bank.id if bank else -1))

    from app.models import Account  # late: keeps the import list above short

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
            Bank.code,
            Bank.name,
            Account.account_number_last4,
        )
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .outerjoin(Account, Transaction.account_id == Account.id)
        .where(*where)
        .order_by(Transaction.transaction_date, Transaction.document_id, Transaction.seq)
    ).all()

    infos: dict[tuple, AccountInfo] = {}
    key_of: dict[int, tuple] = {}
    unrecognised = 0
    for bank_id, account_id, when, balance, credit, debit, description, category, code, name, last4 in rows:
        key = (bank_id, account_id)
        info = infos.setdefault(key, AccountInfo(code, name, last4, interest.Account()))
        if account_id is not None:
            key_of[account_id] = key
        account = info.data
        # rows arrive in order, so the last row of a day sets that day's closing balance
        if account.points and account.points[-1][0] == when:
            account.points[-1] = (when, Decimal(balance))
        else:
            account.points.append((when, Decimal(balance)))
        if category == INTEREST_CATEGORY and Decimal(credit) > 0:
            account.credits.append((when, Decimal(credit)))
        elif category == TAX_CATEGORY and Decimal(debit) > 0 and any(w in description.upper() for w in TAX_WORDS):
            account.taxes.append((when, Decimal(debit)))
        elif Decimal(credit) > 0 and "INTEREST" in description.upper() and year is not None and when.year == year:
            unrecognised += 1

    # A statement's opening balance is the balance at the end of the day before it starts, so it lets
    # the first days of an account's data count even before its first row.
    for first_day, opening, account_id in db.execute(
        select(Document.period_start, Document.opening_balance, Document.account_id).where(
            Document.id.in_(included), Document.period_start.is_not(None), Document.opening_balance.is_not(None)
        )
    ):
        key = key_of.get(account_id)
        if key is not None:
            before = first_day - timedelta(days=1)
            points = infos[key].data.points
            if all(day != before for day, _ in points):
                points.append((before, Decimal(opening)))
    for account_id, period_end in db.execute(
        select(Document.account_id, func.max(Document.period_end))
        .where(Document.id.in_(included), Document.period_end.is_not(None))
        .group_by(Document.account_id)
    ):
        key = key_of.get(account_id)
        if key is not None:
            infos[key].last_covered = period_end
    for info in infos.values():
        info.data.points.sort(key=lambda p: p[0])
    return list(infos.values()), unrecognised


def as_of(infos: list[AccountInfo]) -> date | None:
    days = [info.data.points[-1][0] for info in infos if info.data.points]
    return max(days) if days else None


def _rate(interest_amount: Decimal, balance_days: Decimal) -> Decimal:
    return (interest_amount / balance_days * 365 * 100).quantize(Decimal("0.01"))


# --- what each bank pays -----------------------------------------------------------------------


@dataclass
class BankRate:
    bank_code: str | None
    bank_name: str | None
    accounts: int
    interest: Decimal  # credited in the window
    average_balance: Decimal  # the interest-paying accounts' average balances, added up
    annual_rate: Decimal


def bank_rates(infos: list[AccountInfo], today: date) -> list[BankRate]:
    since = today - timedelta(days=TRAILING_DAYS)
    grouped: dict[tuple, list[interest.Period]] = defaultdict(list)
    latest_average: dict[tuple, dict[int, Decimal]] = defaultdict(dict)  # per account, its newest average balance
    for number, info in enumerate(infos):
        for period in interest.periods(info.data):
            if period.credited_on > since:
                grouped[(info.bank_code, info.bank_name)].append(period)
                latest_average[(info.bank_code, info.bank_name)][number] = period.average_balance
    result = []
    for (code, name), periods in grouped.items():
        total_interest = sum((p.interest for p in periods), Decimal(0))
        total_days = sum((p.balance_days for p in periods), Decimal(0))
        result.append(
            BankRate(
                bank_code=code,
                bank_name=name,
                accounts=len(latest_average[(code, name)]),
                interest=total_interest,
                average_balance=sum(latest_average[(code, name)].values(), Decimal(0)).quantize(Decimal("0.01")),
                annual_rate=_rate(total_interest, total_days),
            )
        )
    return sorted(result, key=lambda r: r.annual_rate, reverse=True)


# --- a rate that is falling --------------------------------------------------------------------


@dataclass
class RateDrop:
    bank_code: str | None
    bank_name: str | None
    previous_rate: Decimal
    latest_rate: Decimal
    since: date


def rate_drops(infos: list[AccountInfo]) -> list[RateDrop]:
    """Per bank: is the rate of the latest interest credit clearly below the recent ones?"""
    by_bank: dict[tuple, list[interest.Period]] = defaultdict(list)
    for info in infos:
        by_bank[(info.bank_code, info.bank_name)].extend(interest.periods(info.data))
    drops = []
    for (code, name), periods in by_bank.items():
        periods.sort(key=lambda p: p.credited_on)
        if len(periods) < DROP_MIN_BEFORE + 1:
            continue
        latest = periods[-1]
        before = periods[-1 - DROP_BASELINE : -1]
        baseline = sum((_rate(p.interest, p.balance_days) for p in before), Decimal(0)) / len(before)
        now = _rate(latest.interest, latest.balance_days)
        if baseline - now >= DROP_POINTS:
            drops.append(RateDrop(code, name, baseline.quantize(Decimal("0.01")), now, latest.credited_on))
    return drops


# --- money that may be idle --------------------------------------------------------------------


@dataclass
class IdleAccount:
    bank_code: str | None
    bank_name: str | None
    last4: str | None
    average_balance: Decimal  # over the last 90 days
    could_earn_a_year: Decimal | None  # at the best rate any of your accounts paid; None if none paid
    best_rate: Decimal | None


def idle_accounts(infos: list[AccountInfo], today: date, best_rate: Decimal | None) -> list[IdleAccount]:
    found = []
    for info in infos:
        points = info.data.points
        if not points:
            continue
        paid_recently = any(day > today - timedelta(days=IDLE_NO_INTEREST_DAYS) for day, _ in info.data.credits)
        if paid_recently:
            continue
        if info.last_covered is not None and (today - info.last_covered).days > 60:
            continue  # its statements stopped (a closed account, or you have not uploaded the newer ones)
        start = max(points[0][0], today - timedelta(days=IDLE_WINDOW_DAYS))
        days = (today - start).days + 1
        total = interest.balance_days(points, start, today + timedelta(days=1))
        if total is None or days < 30:
            continue
        average = total / days
        if average < IDLE_MIN_BALANCE:
            continue
        found.append(
            IdleAccount(
                bank_code=info.bank_code,
                bank_name=info.bank_name,
                last4=info.last4,
                average_balance=average.quantize(Decimal("0.01")),
                could_earn_a_year=(average * best_rate / 100).quantize(Decimal("0.01")) if best_rate else None,
                best_rate=best_rate,
            )
        )
    return sorted(found, key=lambda a: a.average_balance, reverse=True)


# --- where the balance is heading --------------------------------------------------------------


@dataclass
class Projection:
    current_balance: Decimal
    monthly_change: Decimal  # the average change per month over the months used
    months_used: int
    points: list[tuple[date, Decimal]]  # month ends, the next PROJECTION_MONTHS
    months_to_goal: int | None
    goal_reached: bool


def _month_end(year: int, month: int) -> date:
    return date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def projection(infos: list[AccountInfo], today: date, goal: Decimal | None) -> Projection | None:
    """Continue the recent average monthly change of your total balance in a straight line."""
    if not infos:
        return None
    # the last complete month-end, and up to TREND_MONTHS earlier
    end_year, end_month = _add_months(today.year, today.month, -1 if today != _month_end(today.year, today.month) else 0)
    ends = [_month_end(*_add_months(end_year, end_month, -i)) for i in range(TREND_MONTHS, -1, -1)]
    total = lambda day, group: sum((interest.balance_on(i.data.points, day) or Decimal(0) for i in group), Decimal(0))  # noqa: E731

    for first in ends[:-1]:  # the longest window that has data for the accounts that matter
        group = [i for i in infos if interest.balance_on(i.data.points, first) is not None]
        if group:
            months = (ends[-1].year - first.year) * 12 + ends[-1].month - first.month
            if months >= 1:
                change = (total(ends[-1], group) - total(first, group)) / months
                break
    else:
        return None

    current = sum((i.data.points[-1][1] for i in infos if i.data.points), Decimal(0))
    points = []
    year, month = _add_months(today.year, today.month, 0)
    for step in range(1, PROJECTION_MONTHS + 1):
        y, m = _add_months(year, month, step)
        points.append((_month_end(y, m), (current + change * step).quantize(Decimal("0.01"))))

    to_goal = None
    reached = False
    if goal is not None:
        if current >= goal:
            reached = True
        elif change > 0:
            gap = goal - current
            to_goal = int((gap / change).to_integral_value(rounding="ROUND_CEILING"))
    return Projection(
        current_balance=current.quantize(Decimal("0.01")),
        monthly_change=change.quantize(Decimal("0.01")),
        months_used=months,
        points=points,
        months_to_goal=to_goal,
        goal_reached=reached,
    )
