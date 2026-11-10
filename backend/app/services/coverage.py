"""Which stretches of an account's history are covered by statements, and whether
consecutive statements join up.

Two independent checks, both per bank account:

* Missing months: a month between an account's first and last statement that no statement
  covers (see `covered_months` for what "covers" means).
* Balance breaks: two statements that touch (one ends where the next begins) must agree on
  the balance at the join: closing of the first == opening of the second. When they do not,
  transactions are missing between them, or one statement was read wrongly.

Only statements that count in analytics take part in the balance check. Everything here is
exact Decimal comparison; nothing is estimated.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document
from app.services.extraction import ACTIVE_STATUSES

# Statements this many days apart (or fewer) are treated as touching. A statement may start
# on the day the previous one ended, or the day after.
JOIN_TOLERANCE = timedelta(days=1)


def covered_months(period_start: date | None, period_end: date) -> set[tuple[int, int]]:
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


@dataclass
class BalanceBreak:
    from_document_id: int
    to_document_id: int
    on: date  # where the second statement begins
    expected: Decimal  # closing balance of the first statement
    found: Decimal  # opening balance of the second


@dataclass
class AccountCoverage:
    gap_months: list[tuple[int, int]] = field(default_factory=list)
    breaks: list[BalanceBreak] = field(default_factory=list)


def _missing_months(months: set[tuple[int, int]]) -> list[tuple[int, int]]:
    if not months:
        return []
    first, last = min(months), max(months)
    out: list[tuple[int, int]] = []
    year, month = first
    while (year, month) < last:
        year, month = year + (month == 12), month % 12 + 1
        if (year, month) < last and (year, month) not in months:
            out.append((year, month))
    return out


def _breaks(documents: list[Document]) -> list[BalanceBreak]:
    ordered = sorted(
        (
            d
            for d in documents
            if d.status in ACTIVE_STATUSES
            and d.period_start is not None
            and d.period_end is not None
            and d.opening_balance is not None
            and d.closing_balance is not None
        ),
        key=lambda d: (d.period_end, d.id),
    )
    found: list[BalanceBreak] = []
    for before, after in zip(ordered, ordered[1:], strict=False):
        distance = after.period_start - before.period_end
        if abs(distance) > JOIN_TOLERANCE:
            continue  # a real gap or a large overlap: the month check and dedupe handle those
        if before.closing_balance != after.opening_balance:
            found.append(
                BalanceBreak(
                    from_document_id=before.id,
                    to_document_id=after.id,
                    on=after.period_start,
                    expected=before.closing_balance,
                    found=after.opening_balance,
                )
            )
    return found


def account_coverage(db: Session, user_id: int) -> dict[tuple, AccountCoverage]:
    """Coverage per (bank_id, account_id).

    Statements needing review still count for the month check (they are on the tracker) but
    not for the balance check. A statement whose account number was not found sits under
    account None; it can show missing months but never a balance break, because several real
    accounts may be mixed there.
    """
    documents = db.scalars(
        select(Document).where(
            Document.user_id == user_id,
            Document.period_end.is_not(None),
            Document.status.in_(ACTIVE_STATUSES + ("needs_review",)),
        )
    ).all()

    groups: dict[tuple, list[Document]] = {}
    for doc in documents:
        groups.setdefault((doc.bank_id, doc.account_id), []).append(doc)

    report: dict[tuple, AccountCoverage] = {}
    for key, docs in groups.items():
        months: set[tuple[int, int]] = set()
        for doc in docs:
            months |= covered_months(doc.period_start, doc.period_end)
        report[key] = AccountCoverage(
            gap_months=_missing_months(months),
            breaks=_breaks(docs) if key[1] is not None else [],
        )
    return report
