"""Transaction-level duplicate detection across overlapping statements.

Two statements that cover the same dates (a long statement plus a monthly one, or a
re-downloaded copy whose bytes differ) contain the same transactions. The file hash cannot
see that, so rows are compared by `row_hash`: account, date, debit, credit, running balance
and normalised description (docs/00-architecture.md section 4). The running balance makes a
false match practically impossible: two different transactions cannot leave the same balance.

One copy per transaction stays canonical; the others are flagged `is_duplicate` and point at
it. Duplicates remain visible but are excluded from every total.

Which copy is canonical: a statement that counts in analytics (reconciled or accepted) beats
one still needing review; among equals, the earlier upload wins. The flags are recomputed
for the user whenever that could change: after extraction, accepting, and deleting.
"""

from collections import defaultdict

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Document, Transaction

INCLUDED = ("reconciled", "accepted")
_CHUNK = 500  # keeps IN (...) lists well under database parameter limits


def refresh_duplicates(db: Session, user_id: int) -> int:
    """Recompute duplicate flags for one user. Returns how many rows are duplicates.

    Does not commit; the caller owns the transaction.
    """
    repeated = (
        select(Transaction.row_hash)
        .where(Transaction.user_id == user_id)
        .group_by(Transaction.row_hash)
        .having(func.count() > 1)
    )
    rows = db.execute(
        select(
            Transaction.id,
            Transaction.row_hash,
            Transaction.document_id,
            Transaction.seq,
            Document.status,
        )
        .join(Document, Document.id == Transaction.document_id)
        .where(Transaction.user_id == user_id, Transaction.row_hash.in_(repeated))
    ).all()

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row.row_hash].append(row)

    wanted: dict[int, int] = {}  # duplicate row id -> canonical row id
    for members in groups.values():
        members.sort(
            key=lambda r: (0 if r.status in INCLUDED else 1, r.document_id, r.seq)
        )
        canonical = members[0]
        for row in members[1:]:
            # Identical rows inside the SAME statement are separate real transactions.
            if row.document_id != canonical.document_id:
                wanted[row.id] = canonical.id

    current = dict(
        db.execute(
            select(Transaction.id, Transaction.duplicate_of_id).where(
                Transaction.user_id == user_id, Transaction.is_duplicate.is_(True)
            )
        ).all()
    )

    stale = [row_id for row_id in current if row_id not in wanted]
    for start in range(0, len(stale), _CHUNK):
        db.execute(
            update(Transaction)
            .where(Transaction.id.in_(stale[start : start + _CHUNK]))
            .values(is_duplicate=False, duplicate_of_id=None)
        )

    for row_id, canonical_id in wanted.items():
        if row_id not in current or current[row_id] != canonical_id:
            db.execute(
                update(Transaction)
                .where(Transaction.id == row_id)
                .values(is_duplicate=True, duplicate_of_id=canonical_id)
            )

    return len(wanted)


def refresh_all_users(db: Session) -> int:
    """Backfill for rows that existed before the duplicate columns. Idempotent."""
    total = 0
    for (user_id,) in db.execute(select(Transaction.user_id).distinct()).all():
        total += refresh_duplicates(db, user_id)
    db.commit()
    return total
