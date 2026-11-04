import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Category, Document, UserSession
from app.routers.overview import _bank_split, _top_expenses, _totals
from app.routers.transactions import _safe
from app.services import budgets
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api/reports", tags=["reports"])

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


@router.get("/monthly.csv")
def monthly_csv(
    year: int = Query(default=None, ge=2000, le=2100),
    month: int = Query(default=None, ge=1, le=12),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    """A one-month summary as CSV: totals, categories, banks, budgets and the largest
    expenses. Same rules as the dashboard: transfers and repeated rows are left out, and only
    reconciled or accepted statements count."""
    today = date.today()
    year, month = year or today.year, month or today.month
    start, end = budgets.month_bounds(year, month)

    included = select(Document.id).where(
        Document.user_id == session.user_id, Document.status.in_(ACTIVE_STATUSES)
    )
    categories = {
        c.id: c for c in db.scalars(select(Category).where(Category.user_id == session.user_id))
    }
    totals, by_category = _totals(db, included, start, end, categories)

    buffer = io.StringIO()
    out = csv.writer(buffer)
    out.writerow([f"Monthly summary: {MONTHS[month - 1]} {year}"])
    out.writerow(["Currency", "LKR"])
    out.writerow([])

    out.writerow(["Totals"])
    for label, value in (
        ("Income", totals.income),
        ("Expense", totals.expense),
        ("Net", totals.net),
        ("Transfers in (not counted above)", totals.transfers_in),
        ("Transfers out (not counted above)", totals.transfers_out),
        ("Transactions", totals.transactions),
        ("Uncategorised", totals.uncategorised),
    ):
        out.writerow([label, value])
    out.writerow([])

    out.writerow(["By category", "Income", "Expense", "Transactions"])
    for c in by_category:
        out.writerow([_safe(c.name), c.income, c.expense, c.transactions])
    out.writerow([])

    out.writerow(["By bank", "Income", "Expense", "Net", "Transactions"])
    for b in _bank_split(db, included, start, end, categories):
        out.writerow([_safe(b.bank_name or "Unknown bank"), b.income, b.expense, b.net, b.transactions])
    out.writerow([])

    lines = budgets.lines(db, session.user_id, year, month)
    if lines:
        out.writerow(["Budgets", "Limit", "Spent", "Remaining", "Used %", "State"])
        for b in lines:
            out.writerow([_safe(b.category_name), b.limit, b.spent, b.remaining, b.percent, b.state])
        out.writerow([])

    out.writerow(["Largest expenses", "Date", "Amount", "Category"])
    for t in _top_expenses(db, included, start, end, categories, None, limit=10):
        out.writerow(
            [_safe(t.description), t.transaction_date.isoformat(), t.amount, _safe(t.category_name or "")]
        )

    name = f"summary-{year}-{month:02d}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),  # BOM so Excel reads the text as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
