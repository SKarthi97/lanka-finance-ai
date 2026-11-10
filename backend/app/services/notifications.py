"""Things that need the user's attention, worked out from the data each time they are asked for.

Nothing is stored: a notice exists while its cause does. Upload the missing statement and the
notice is gone. Text is built from bank names, the last four digits of an account and dates;
never from descriptions or amounts.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Document, Transaction
from app.services import transfers
from app.services.coverage import account_coverage
from app.services.extraction import ACTIVE_STATUSES
from app.tuning import STALE_DAYS  # noqa: F401

# An account whose latest statement ended longer ago than this is "out of date"; the dashboard
# uses the same number for its "out of date" flag.

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class Notice:
    key: str  # stable id, e.g. "stale:3:7"
    kind: str  # stale | gap | break | review | transfers
    severity: str  # warn | info
    text: str
    href: str


def _label(doc: Document) -> str:
    bank = doc.bank.name if doc.bank else "Unknown bank"
    return f"{bank} •••• {doc.account.account_number_last4}" if doc.account else bank


def _month_list(months: list[tuple[int, int]], limit: int = 4) -> str:
    names = [f"{MONTHS[m - 1]} {y}" for y, m in months[:limit]]
    more = len(months) - limit
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def collect(db: Session, user_id: int, today: date | None = None) -> list[Notice]:
    today = today or date.today()
    notices: list[Notice] = []

    # Out-of-date accounts: the latest counted statement per bank account.
    latest: dict[tuple, Document] = {}
    for doc in db.scalars(
        select(Document)
        .where(
            Document.user_id == user_id,
            Document.status.in_(ACTIVE_STATUSES),
            Document.period_end.is_not(None),
        )
        .order_by(Document.period_end, Document.id)
    ):
        latest[(doc.bank_id, doc.account_id)] = doc
    for key, doc in latest.items():
        age = (today - doc.period_end).days
        if age > STALE_DAYS:
            notices.append(
                Notice(
                    key=f"stale:{key[0]}:{key[1]}",
                    kind="stale",
                    severity="warn",
                    text=(
                        f"{_label(doc)}: the latest statement ends {doc.period_end.day} "
                        f"{MONTHS[doc.period_end.month - 1]} {doc.period_end.year} ({age} days ago). "
                        "Upload the newer statement to keep it up to date."
                    ),
                    href="/upload",
                )
            )

    # Statements that did not reconcile are left out of every figure until you decide.
    waiting = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.user_id == user_id, Document.status == "needs_review")
    ) or 0
    if waiting:
        notices.append(
            Notice(
                key="review",
                kind="review",
                severity="warn",
                text=(
                    f"{waiting} statement{'s' if waiting != 1 else ''} did not reconcile and "
                    f"{'are' if waiting != 1 else 'is'} left out of every figure until you review."
                ),
                href="/upload",
            )
        )

    # Missing months and balance breaks, per account.
    docs_by_key = dict(latest)
    for key, coverage in account_coverage(db, user_id).items():
        doc = docs_by_key.get(key)
        label = _label(doc) if doc else "An account"
        if coverage.gap_months:
            notices.append(
                Notice(
                    key=f"gap:{key[0]}:{key[1]}",
                    kind="gap",
                    severity="warn",
                    text=f"{label}: no statement for {_month_list(coverage.gap_months)}.",
                    href="/",
                )
            )
        if coverage.breaks:
            count = len(coverage.breaks)
            notices.append(
                Notice(
                    key=f"break:{key[0]}:{key[1]}",
                    kind="break",
                    severity="warn",
                    text=(
                        f"{label}: {count} statement{'s do' if count != 1 else ' does'} not start "
                        "from the previous closing balance, so transactions may be missing."
                    ),
                    href="/",
                )
            )

    pairs = len(transfers.find_pairs(db, user_id))
    if pairs:
        notices.append(
            Notice(
                key="transfers",
                kind="transfers",
                severity="info",
                text=(
                    f"{pairs} possible transfer{'s' if pairs != 1 else ''} between your own "
                    "accounts, counted as income and expense until you confirm."
                ),
                href="/categories?tab=transfers",
            )
        )

    # An interest rate that fell: worked out only when some interest was ever credited (cheap check first).
    has_interest = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == user_id, Category.name == "Interest income", Transaction.credit > 0)
        .limit(1)
    )
    if has_interest:
        from app.services import savings  # late: it reads every row of the user's accounts

        infos, _ = savings.load_accounts(db, user_id)
        for drop in savings.rate_drops(infos):
            notices.append(
                Notice(
                    key=f"rate:{drop.bank_code}",
                    kind="rate",
                    severity="info",
                    text=(
                        f"{drop.bank_name or 'A bank'}: the interest you are getting fell from about "
                        f"{drop.previous_rate}% to {drop.latest_rate}% a year (credit on "
                        f"{drop.since.day} {MONTHS[drop.since.month - 1]} {drop.since.year})."
                    ),
                    href="/savings",
                )
            )
    return notices
