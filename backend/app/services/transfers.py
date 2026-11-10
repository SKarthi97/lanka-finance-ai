"""Find money that moved between your own accounts.

A transfer shows up twice: a debit in one account and a credit of the same amount in another,
usually on the same day or a day or two apart. Suggesting the pair, and letting you confirm
it, keeps both sides out of income and expense.

Matching is deliberately strict and entirely local arithmetic: equal amounts to the cent,
different accounts, dates within `WINDOW_DAYS`, one-to-one. Nothing is changed until you
confirm; a pair you reject is remembered (by row hash, so it survives re-extraction).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    Bank,
    Category,
    Document,
    Transaction,
    TransferRejection,
)
from app.services.extraction import ACTIVE_STATUSES
from app.tuning import TRANSFER_WINDOW_DAYS as WINDOW_DAYS

ZERO = Decimal("0.00")


@dataclass
class Side:
    id: int
    date: date
    description: str
    amount: Decimal
    bank_code: str | None
    account_last4: str | None
    row_hash: str
    account_key: tuple
    is_transfer: bool


@dataclass
class Pair:
    out: Side  # the debit (money leaving)
    into: Side  # the credit (money arriving)
    days_apart: int
    ambiguous: bool  # another row could equally be the other half


def pair_key(hash_one: str, hash_two: str) -> tuple[str, str]:
    return (hash_one, hash_two) if hash_one <= hash_two else (hash_two, hash_one)


def transfer_category(db: Session, user_id: int) -> Category | None:
    """The category a confirmed transfer is filed under: "Transfers" if present, otherwise
    any category of kind transfer."""
    categories = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.kind == "transfer")
    ).all()
    for category in categories:
        if category.name == "Transfers":
            return category
    return min(categories, key=lambda c: c.id, default=None)


def _side(row: Transaction, bank_code, last4, kind, amount: Decimal) -> Side:
    return Side(
        id=row.id,
        date=row.transaction_date,
        description=row.original_description,
        amount=amount,
        bank_code=bank_code,
        account_last4=last4,
        row_hash=row.row_hash,
        account_key=(row.bank_id, row.account_id),
        is_transfer=kind == "transfer",
    )


def find_pairs(db: Session, user_id: int) -> list[Pair]:
    """Suggested own-account transfers, oldest first."""
    rejected = {
        (r.hash_a, r.hash_b)
        for r in db.scalars(select(TransferRejection).where(TransferRejection.user_id == user_id))
    }

    rows = db.execute(
        select(Transaction, Bank.code, Account.account_number_last4, Category.kind)
        .join(Document, Document.id == Transaction.document_id)
        .outerjoin(Bank, Bank.id == Transaction.bank_id)
        .outerjoin(Account, Account.id == Transaction.account_id)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.is_duplicate.is_(False),
            Document.status.in_(ACTIVE_STATUSES),
        )
    ).all()

    outs: list[Side] = []
    credits_by_amount: dict[Decimal, list[Side]] = {}
    for row, bank_code, last4, kind in rows:
        # A category you chose yourself (other than a transfer) is your decision: leave it.
        if row.classification_source == "manual" and kind != "transfer" and row.category_id:
            continue
        if row.debit > ZERO:
            outs.append(_side(row, bank_code, last4, kind, row.debit))
        elif row.credit > ZERO:
            credits_by_amount.setdefault(row.credit, []).append(
                _side(row, bank_code, last4, kind, row.credit)
            )

    candidates: list[tuple[int, int, int, Side, Side]] = []
    out_options: dict[int, int] = {}
    in_options: dict[int, int] = {}
    for out in outs:
        for incoming in credits_by_amount.get(out.amount, []):
            if out.account_key == incoming.account_key:
                continue
            days = abs((incoming.date - out.date).days)
            if days > WINDOW_DAYS:
                continue
            if out.is_transfer and incoming.is_transfer:
                continue  # both halves already filed as a transfer
            if pair_key(out.row_hash, incoming.row_hash) in rejected:
                continue
            candidates.append((days, out.id, incoming.id, out, incoming))
            out_options[out.id] = out_options.get(out.id, 0) + 1
            in_options[incoming.id] = in_options.get(incoming.id, 0) + 1

    # Closest dates first, then by id so the result never depends on database order.
    candidates.sort(key=lambda c: c[:3])
    used_out: set[int] = set()
    used_in: set[int] = set()
    pairs: list[Pair] = []
    for days, out_id, in_id, out, incoming in candidates:
        if out_id in used_out or in_id in used_in:
            continue
        used_out.add(out_id)
        used_in.add(in_id)
        pairs.append(
            Pair(
                out=out,
                into=incoming,
                days_apart=days,
                ambiguous=out_options[out_id] > 1 or in_options[in_id] > 1,
            )
        )
    pairs.sort(key=lambda p: (p.out.date, p.out.id))
    return pairs
