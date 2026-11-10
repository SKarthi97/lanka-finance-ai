"""Answer a question with a number worked out by code: "how much did I spend on fuel in March?".

The words only choose WHICH sum, count, average or largest row to compute. The filters come from
`search.interpret` (the same ones that fill the Transactions page), and the arithmetic is exact
Decimal over your own statements. No model writes the answer and nothing is estimated.
Transfers between your own accounts, repeated rows and statements still in review are left out,
the same as in the reports.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, Transaction

CENTS = Decimal("0.01")
ACTIVE = ("reconciled", "accepted")

_COUNT = re.compile(r"\b(how many|number of|count)\b")
_AVERAGE = re.compile(r"\b(average|avg|mean)\b")
_LARGEST = re.compile(r"\b(largest|biggest|highest|most expensive|top)\b")
_SMALLEST = re.compile(r"\b(smallest|lowest|cheapest|least expensive)\b")
_SUM = re.compile(r"\b(how much|total|sum)\b")


@dataclass
class Part:
    label: str  # "Money out" / "Money in"
    value: str | None  # the number, as text with two decimals (None: nothing matched)
    count: int
    detail: str | None = None  # largest/smallest: the row's date and description


@dataclass
class Answer:
    kind: str  # sum | count | average | largest | smallest
    heading: str
    parts: list[Part] = field(default_factory=list)


def detect(text: str) -> str | None:
    low = " ".join(text.lower().split())
    for kind, pattern in (
        ("count", _COUNT),
        ("average", _AVERAGE),
        ("largest", _LARGEST),
        ("smallest", _SMALLEST),
        ("sum", _SUM),
    ):
        if pattern.search(low):
            return kind
    return None


HEADINGS = {
    "sum": "Total",
    "count": "Number of transactions",
    "average": "Average per transaction",
    "largest": "Largest transaction",
    "smallest": "Smallest transaction",
}


def compute(db: Session, user_id: int, conditions: list, kind: str, direction: str | None) -> Answer:
    """`conditions` are the Transactions filters (already allow-listed); added here: only
    statements that count, no repeated rows, no transfers."""
    from app.models import Bank, Category  # local: keeps the module import light

    base = (
        select(Transaction)
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(
            *conditions,
            Transaction.document_id.in_(
                select(Document.id).where(Document.user_id == user_id, Document.status.in_(ACTIVE))
            ),
            Transaction.is_duplicate.is_(False),
            (Category.kind.is_(None)) | (Category.kind != "transfer"),
        )
    )
    answer = Answer(kind=kind, heading=HEADINGS[kind])
    sides = [("out", "Money out")] if direction == "out" else [("in", "Money in")] if direction == "in" else [("out", "Money out"), ("in", "Money in")]

    for side, label in sides:
        column = Transaction.debit if side == "out" else Transaction.credit
        rows = base.where(column > 0).subquery()
        amount = rows.c.debit if side == "out" else rows.c.credit
        count = db.scalar(select(func.count()).select_from(rows)) or 0
        if count == 0:
            answer.parts.append(Part(label, None, 0))
            continue
        if kind == "count":
            answer.parts.append(Part(label, str(count), count))
        elif kind in ("sum", "average"):
            total = Decimal(str(db.scalar(select(func.sum(amount)).select_from(rows)) or 0))
            value = total if kind == "sum" else total / count
            answer.parts.append(Part(label, str(value.quantize(CENTS)), count))
        else:
            order = amount.desc() if kind == "largest" else amount.asc()
            top = db.execute(select(rows.c.transaction_date, rows.c.original_description, amount).order_by(order).limit(1)).one()
            answer.parts.append(
                Part(label, str(Decimal(str(top[2])).quantize(CENTS)), count, f"{top[0].isoformat()} · {top[1][:80]}")
            )
    return answer
