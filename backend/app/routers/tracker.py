"""Which months have a statement, per bank and account (GET /api/tracker)."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Document, UserSession
from app.routers.overview import _transaction_years
from app.services.coverage import account_coverage, covered_months
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api", tags=["overview"])


# --- statement tracker ---------------------------------------------------------


class TrackerCell(BaseModel):
    status: str  # ok | review
    document_id: int


class TrackerBreak(BaseModel):
    from_document_id: int
    to_document_id: int
    on: date
    expected: Decimal  # closing balance of the earlier statement
    found: Decimal  # opening balance of the later statement


class TrackerRow(BaseModel):
    bank_code: str | None
    bank_name: str | None
    account_last4: str | None
    cells: dict[int, TrackerCell]  # month number -> cell
    gap_months: list[int] = []  # months of the selected year missing between two statements
    gap_total: int = 0  # missing months in every year
    breaks: list[TrackerBreak] = []  # balance breaks between consecutive statements


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

    covered = {d.id: covered_months(d.period_start, d.period_end) for d in docs}
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

    report = account_coverage(db, session.user_id)
    for key, row in rows.items():
        coverage = report.get(key)
        if coverage is None:
            continue
        row.gap_months = [m for y, m in coverage.gap_months if y == year]
        row.gap_total = len(coverage.gap_months)
        row.breaks = [
            TrackerBreak(
                from_document_id=b.from_document_id,
                to_document_id=b.to_document_id,
                on=b.on,
                expected=b.expected,
                found=b.found,
            )
            for b in coverage.breaks
        ]

    ordered = sorted(rows.values(), key=lambda r: (r.bank_name or "", r.account_last4 or ""))
    return TrackerOut(year=year, years=years, rows=ordered)
