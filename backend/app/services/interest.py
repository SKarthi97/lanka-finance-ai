"""The interest rate your accounts actually paid, worked out from the statements.

Banks pay savings interest on the money you keep each day: every day the end-of-day balance earns
balance x annual rate / 365, and the total is credited later (often at the start of the next
month, so a credit in March is usually for February). This module reverses that:

    annual rate = interest credited / (sum of the end-of-day balances over the days it covers) x 365

The days it covers run from the previous interest credit of the same account up to the day before
this one. For an account's first credit in the data there is no earlier credit, so the previous
calendar month is assumed; when the statements do not reach back that far, a credit paid late in a
month is taken to be for that month itself (and the result says so).

All of this is arithmetic on figures from the statements; nothing here is estimated by a model.
The result is an estimate of the bank's rate (rounding and day-count rules differ), not the rate
printed in the bank's terms.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.tuning import MIN_ASSUMED_DAYS, MIN_SAME_MONTH_DAYS, TAX_WINDOW_DAYS  # noqa: F401

SAME_MONTH = "the month it was credited in"


@dataclass
class Account:
    """One account's end-of-day balances and its interest lines. `points` is sorted by date."""

    points: list[tuple[date, Decimal]] = field(default_factory=list)  # (day, balance after the day's last row)
    credits: list[tuple[date, Decimal]] = field(default_factory=list)  # interest credited
    taxes: list[tuple[date, Decimal]] = field(default_factory=list)  # tax withheld on interest


@dataclass
class Period:
    """One interest credit and the days it pays for."""

    credited_on: date
    start: date
    days: int
    interest: Decimal
    tax: Decimal
    balance_days: Decimal  # sum over the days of the end-of-day balance
    assumed: str | None = None  # how the start was guessed, when there was no earlier credit

    @property
    def average_balance(self) -> Decimal:
        return self.balance_days / self.days


def balance_on(points: list[tuple[date, Decimal]], day: date) -> Decimal | None:
    """The balance at the end of `day`: that of the last row on or before it; None before the data."""
    index = bisect_right([p[0] for p in points], day)
    return points[index - 1][1] if index else None


def balance_days(points: list[tuple[date, Decimal]], start: date, end: date) -> Decimal | None:
    """Sum of end-of-day balances for every day from `start` up to (not including) `end`.
    None when the statements do not reach back to `start`."""
    days = [p[0] for p in points]
    if not points or start < days[0] or end <= start:
        return None
    total = Decimal(0)
    day = start
    while day < end:
        total += points[bisect_right(days, day) - 1][1]
        day += timedelta(days=1)
    return total


def previous_month_start(day: date) -> date:
    first = day.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def periods(account: Account) -> list[Period]:
    """Every interest credit of one account that has enough data to judge."""
    found: list[Period] = []
    credits = sorted(account.credits)
    for index, (credited_on, interest) in enumerate(credits):
        assumed = None
        if index > 0:
            start = credits[index - 1][0]
            total = balance_days(account.points, start, credited_on)
        else:
            # No earlier credit: usually the previous month. When the statements do not reach back
            # that far, a credit paid late in a month is taken to be for that month itself.
            start = previous_month_start(credited_on)
            total = None
            if (credited_on - start).days >= MIN_ASSUMED_DAYS:
                total = balance_days(account.points, start, credited_on)
            if total is None:
                start = credited_on.replace(day=1)
                if (credited_on - start).days >= MIN_SAME_MONTH_DAYS:
                    total = balance_days(account.points, start, credited_on)
                    assumed = SAME_MONTH
        if total is None or total <= 0:
            continue
        tax = sum(
            (amount for when, amount in account.taxes if credited_on <= when <= credited_on + timedelta(days=TAX_WINDOW_DAYS)),
            Decimal(0),
        )
        found.append(Period(credited_on, start, (credited_on - start).days, interest, tax, total, assumed))
    return found


@dataclass
class MonthRate:
    month: int
    interest: Decimal  # everything credited in the month, after tax, whether or not a rate could be worked out
    tax: Decimal
    average_balance: Decimal | None  # the accounts' average balances over their periods, added up
    days: int  # the longest period behind the figure
    annual_rate: Decimal | None  # percent a year, on the net interest; None when there is too little data
    monthly_rate: Decimal | None  # annual / 12
    assumed: str | None = None  # SAME_MONTH when the start of the period had to be guessed
    unrated: int = 0  # credits in the month with too little data behind them for a rate


def monthly_rates(accounts: list[Account], year: int) -> list[MonthRate]:
    """Per month of `year` with an interest credit: what was credited and the rate it works out to."""
    by_month: dict[int, list[Period]] = {}
    credited: dict[int, Decimal] = {}
    counted: dict[int, int] = {}
    for account in accounts:
        for when, amount in account.credits:
            if when.year == year:
                credited[when.month] = credited.get(when.month, Decimal(0)) + amount
                counted[when.month] = counted.get(when.month, 0) + 1
        for period in periods(account):
            if period.credited_on.year == year:
                by_month.setdefault(period.credited_on.month, []).append(period)

    result = []
    for month in sorted(credited):
        items = by_month.get(month, [])
        rated = sum((p.interest for p in items), Decimal(0))
        total_days = sum((p.balance_days for p in items), Decimal(0))
        annual = rated / total_days * 365 * 100 if items else None
        result.append(
            MonthRate(
                month=month,
                interest=credited[month],
                tax=sum((p.tax for p in items), Decimal(0)),
                average_balance=sum((p.average_balance for p in items), Decimal(0)) if items else None,
                days=max((p.days for p in items), default=0),
                annual_rate=annual.quantize(Decimal("0.01")) if annual is not None else None,
                monthly_rate=(annual / 12).quantize(Decimal("0.01")) if annual is not None else None,
                assumed=next((p.assumed for p in items if p.assumed), None),
                unrated=counted[month] - len(items),
            )
        )
    return result
