"""Find payments and income that repeat on a schedule.

Plain arithmetic on dates and amounts, no model. Rows are grouped by the reusable part of
their description (`description_stem`) and direction. A group counts as recurring when it has
enough occurrences, the gaps between them cluster around a known cadence, and the amounts
stay close to their median.

Limits, stated plainly: a bill whose amount swings by more than 20% (for example electricity)
is not detected, and two merchants whose descriptions share their first words are grouped
together (the amount check usually separates them).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Document, Transaction
from app.services.categorizer import description_stem
from app.services.extraction import ACTIVE_STATUSES

ZERO = Decimal("0.00")
AMOUNT_TOLERANCE = Decimal("0.20")  # an amount within 20% of the median counts as "the same"
SHARE = 0.75  # this share of gaps / amounts must fit

# name, centre in days, allowed distance from the centre, fewest occurrences
CADENCES = (
    ("weekly", 7, 2, 4),
    ("fortnightly", 14, 3, 4),
    ("monthly", 30, 5, 3),
    ("quarterly", 91, 8, 3),
    ("yearly", 365, 15, 2),
)


@dataclass
class Recurring:
    stem: str
    direction: str  # expense | income
    cadence: str
    count: int
    typical_amount: Decimal
    last_date: date
    next_expected: date
    state: str  # upcoming | due | overdue | ended
    category_name: str | None
    monthly_equivalent: Decimal  # what it costs (or brings in) per month on average


def _near(amount: Decimal, centre: Decimal) -> bool:
    return centre > 0 and abs(amount - centre) <= centre * AMOUNT_TOLERANCE


def _cadence(gaps: list[int], count: int) -> tuple[str, int] | None:
    middle = median(gaps)
    for name, centre, slack, fewest in CADENCES:
        if count < fewest or abs(middle - centre) > slack:
            continue
        fitting = sum(1 for g in gaps if abs(g - centre) <= slack * 2)
        if fitting / len(gaps) >= SHARE:
            return name, centre
    return None


def _state(last: date, interval: int, today: date) -> tuple[str, date]:
    expected = last + timedelta(days=interval)
    grace = timedelta(days=max(3, interval // 6))
    if today <= expected - grace:
        return "upcoming", expected
    if today <= expected + grace:
        return "due", expected
    if today <= last + timedelta(days=interval * 2 + int(grace.days)):
        return "overdue", expected
    return "ended", expected


def find(db: Session, user_id: int, today: date | None = None) -> list[Recurring]:
    today = today or date.today()
    rows = db.execute(
        select(
            Transaction.transaction_date,
            Transaction.original_description,
            Transaction.debit,
            Transaction.credit,
            Transaction.category_id,
        )
        .join(Document, Document.id == Transaction.document_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.is_duplicate.is_(False),
            Document.status.in_(ACTIVE_STATUSES),
        )
    ).all()
    categories = {
        c.id: c for c in db.scalars(select(Category).where(Category.user_id == user_id))
    }

    groups: dict[tuple[str, str], list[tuple[date, Decimal, int | None]]] = {}
    for when, description, debit, credit, category_id in rows:
        category = categories.get(category_id)
        if category is not None and category.kind == "transfer":
            continue  # moving your own money is not a bill
        stem = description_stem(description)
        if not stem:
            continue
        direction, amount = ("expense", debit) if debit > 0 else ("income", credit)
        if amount <= 0:
            continue
        groups.setdefault((direction, stem), []).append((when, Decimal(amount), category_id))

    found: list[Recurring] = []
    for (direction, stem), items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda i: i[0])
        dates = [i[0] for i in items]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue  # several rows on one day are one event, not a schedule
        cadence = _cadence(gaps, len(items))
        if cadence is None:
            continue
        name, interval = cadence

        typical = Decimal(str(median(i[1] for i in items))).quantize(Decimal("0.01"))
        if sum(1 for i in items if _near(i[1], typical)) / len(items) < SHARE:
            continue

        state, expected = _state(dates[-1], interval, today)
        # The category on the most recent row, which is the one you would see today.
        category = categories.get(items[-1][2])
        found.append(
            Recurring(
                stem=stem,
                direction=direction,
                cadence=name,
                count=len(items),
                typical_amount=typical,
                last_date=dates[-1],
                next_expected=expected,
                state=state,
                category_name=category.name if category else None,
                monthly_equivalent=(typical * Decimal(30) / Decimal(interval)).quantize(
                    Decimal("0.01")
                ),
            )
        )
    order = {"overdue": 0, "due": 1, "upcoming": 2, "ended": 3}
    found.sort(key=lambda r: (order[r.state], r.next_expected, r.stem))
    return found
