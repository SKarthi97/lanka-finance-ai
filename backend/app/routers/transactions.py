import csv
import io
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Account, Bank, Category, Transaction, UserSession

router = APIRouter(prefix="/api", tags=["transactions"])

MAX_PAGE_SIZE = 500
MAX_EXPORT_ROWS = 100_000

SortKey = Literal["date", "amount", "description", "bank", "category"]


class TransactionOut(BaseModel):
    id: int
    document_id: int
    seq: int
    transaction_date: date
    description: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    source_page: int
    validation_status: str
    bank_code: str | None
    bank_name: str | None
    account_last4: str | None
    is_duplicate: bool
    duplicate_of_id: int | None
    category_id: int | None
    category_name: str | None
    category_kind: str | None
    classification_source: str | None
    classification_confidence: float | None
    classification_explanation: str | None


class TransactionList(BaseModel):
    total: int
    items: list[TransactionOut]


class Filters(BaseModel):
    """The filters shared by the list and the CSV export."""

    document_id: int | None = None
    bank_code: str | None = None
    category_id: int | None = None
    uncategorised: bool = False
    year: int | None = None
    month: int | None = None
    validation_status: str | None = None
    flagged: bool = False
    duplicates: Literal["hide", "show", "only"] = "hide"
    q: str | None = None


def _conditions(user_id: int, f: Filters) -> list:
    conditions = [Transaction.user_id == user_id]
    if f.document_id is not None:
        conditions.append(Transaction.document_id == f.document_id)
    if f.bank_code:
        conditions.append(Bank.code == f.bank_code)
    if f.category_id is not None:
        conditions.append(Transaction.category_id == f.category_id)
    if f.uncategorised:
        conditions.append(Transaction.category_id.is_(None))
    if f.year is not None:
        # A month only makes sense within a year.
        start = date(f.year, f.month or 1, 1)
        if f.month is None:
            end = date(f.year + 1, 1, 1)
        else:
            end = date(f.year + (f.month == 12), f.month % 12 + 1, 1)
        conditions += [Transaction.transaction_date >= start, Transaction.transaction_date < end]
    if f.validation_status:
        conditions.append(Transaction.validation_status == f.validation_status)
    if f.duplicates == "hide":
        conditions.append(Transaction.is_duplicate.is_(False))
    elif f.duplicates == "only":
        conditions.append(Transaction.is_duplicate.is_(True))
    if f.flagged:  # any row that did not pass every check
        conditions.append(Transaction.validation_status != "ok")
    if f.q:
        conditions.append(Transaction.original_description.ilike(f"%{f.q.strip()}%"))
    return conditions


def _ordering(sort: SortKey, order: Literal["asc", "desc"]) -> list:
    column = {
        "date": Transaction.transaction_date,
        "amount": Transaction.debit + Transaction.credit,
        "description": func.lower(Transaction.original_description),
        "bank": Bank.name,
        "category": Category.name,
    }[sort]
    primary = column.asc() if order == "asc" else column.desc()
    # Stable, readable ties: newest statement row first within equal values.
    return [
        primary,
        Transaction.transaction_date.desc(),
        Transaction.document_id.desc(),
        Transaction.seq.desc(),
    ]


def _query(conditions: list):
    return (
        select(
            Transaction, Bank.code, Bank.name, Account.account_number_last4, Category.name, Category.kind
        )
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .outerjoin(Account, Transaction.account_id == Account.id)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(*conditions)
    )


@router.get("/transactions", response_model=TransactionList)
def list_transactions(
    document_id: int | None = None,
    bank_code: str | None = Query(default=None, max_length=32),
    category_id: int | None = None,
    uncategorised: bool = False,
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    validation_status: str | None = None,
    flagged: bool = False,
    duplicates: Literal["hide", "show", "only"] = "hide",
    q: str | None = Query(default=None, max_length=100),
    sort: SortKey = "date",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> TransactionList:
    conditions = _conditions(
        session.user_id,
        Filters(
            document_id=document_id,
            bank_code=bank_code,
            category_id=category_id,
            uncategorised=uncategorised,
            year=year,
            month=month,
            validation_status=validation_status,
            flagged=flagged,
            duplicates=duplicates,
            q=q,
        ),
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Transaction)
            .outerjoin(Bank, Transaction.bank_id == Bank.id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        _query(conditions).order_by(*_ordering(sort, order)).limit(limit).offset(offset)
    ).all()

    return TransactionList(
        total=total,
        items=[
            TransactionOut(
                id=t.id,
                document_id=t.document_id,
                seq=t.seq,
                transaction_date=t.transaction_date,
                description=t.original_description,
                debit=t.debit,
                credit=t.credit,
                running_balance=t.running_balance,
                source_page=t.source_page,
                validation_status=t.validation_status,
                bank_code=bank_code_,
                bank_name=bank_name,
                account_last4=last4,
                is_duplicate=t.is_duplicate,
                duplicate_of_id=t.duplicate_of_id,
                category_id=t.category_id,
                category_name=category_name,
                category_kind=category_kind,
                classification_source=t.classification_source,
                classification_confidence=t.classification_confidence,
                classification_explanation=t.classification_explanation,
            )
            for t, bank_code_, bank_name, last4, category_name, category_kind in rows
        ],
    )


# --- CSV export ----------------------------------------------------------------------------------

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(cell: str) -> str:
    """A spreadsheet would run a cell that starts with = + - @ as a formula. Descriptions come
    from a PDF, so they are neutralised with a leading apostrophe."""
    return "'" + cell if cell.startswith(_FORMULA_PREFIXES) else cell


@router.get("/transactions/export.csv")
def export_transactions(
    document_id: int | None = None,
    bank_code: str | None = Query(default=None, max_length=32),
    category_id: int | None = None,
    uncategorised: bool = False,
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    validation_status: str | None = None,
    flagged: bool = False,
    duplicates: Literal["hide", "show", "only"] = "hide",
    q: str | None = Query(default=None, max_length=100),
    sort: SortKey = "date",
    order: Literal["asc", "desc"] = "desc",
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """The transactions matching the current filters as a CSV file (the whole result, not one
    page). Amounts are exact decimals; nothing leaves your machine."""
    conditions = _conditions(
        session.user_id,
        Filters(
            document_id=document_id,
            bank_code=bank_code,
            category_id=category_id,
            uncategorised=uncategorised,
            year=year,
            month=month,
            validation_status=validation_status,
            flagged=flagged,
            duplicates=duplicates,
            q=q,
        ),
    )
    rows = db.execute(
        _query(conditions).order_by(*_ordering(sort, order)).limit(MAX_EXPORT_ROWS)
    ).all()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "date",
                "bank",
                "account_last4",
                "description",
                "debit",
                "credit",
                "balance",
                "category",
                "kind",
                "duplicate",
            ]
        )
        yield "﻿" + buffer.getvalue()  # BOM so Excel reads UTF-8
        for t, _code, bank_name, last4, category_name, kind in rows:
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(
                [
                    t.transaction_date.isoformat(),
                    _safe(bank_name or ""),
                    last4 or "",
                    _safe(t.original_description),
                    f"{t.debit:.2f}",
                    f"{t.credit:.2f}",
                    f"{t.running_balance:.2f}",
                    _safe(category_name or ""),
                    kind or "",
                    "yes" if t.is_duplicate else "",
                ]
            )
            yield buffer.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )
