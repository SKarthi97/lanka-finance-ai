"""Statements that are not PDFs: a CSV file or rows typed by hand (see services/importer.py)."""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import importer
from app.services.llm_classifier import enqueue_classification
from app.services.merchants import enqueue_naming

log = logging.getLogger("imports")
router = APIRouter(prefix="/api/imports", tags=["imports"])

MAX_CSV_BYTES = 5 * 1024 * 1024


class ImportOut(BaseModel):
    document_id: int
    status: str
    rows: int


class ManualRow(BaseModel):
    date: date
    description: str = Field(min_length=1, max_length=300)
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    balance: Decimal | None = None


class ManualIn(BaseModel):
    rows: list[ManualRow] = Field(min_length=1, max_length=importer.MAX_ROWS)
    bank_code: str | None = None
    account_number: str | None = Field(default=None, max_length=40)
    opening_balance: Decimal | None = None


def _fail(status: int, error: importer.ImportError_) -> HTTPException:
    log.info("import rejected: %s", error.code)  # a code and a row number, never row text
    return HTTPException(status, detail={"code": error.code, "row": error.row})


def _run(db, settings, session, rows, **kwargs) -> ImportOut:
    try:
        document = importer.import_rows(db, settings, session.user_id, rows, **kwargs)
    except importer.ImportError_ as error:
        raise _fail(422, error)
    except ValueError:
        raise HTTPException(409, detail={"code": "duplicate", "row": None})
    if enqueue_classification(db, settings, session.user_id) | enqueue_naming(db, settings, session.user_id):
        db.commit()
    return ImportOut(document_id=document.id, status=document.status, rows=len(rows))


@router.post("/csv", response_model=ImportOut, status_code=201)
async def import_csv(
    file: UploadFile = File(...),
    bank_code: str | None = Form(default=None),
    account_number: str | None = Form(default=None),
    opening_balance: Decimal | None = Form(default=None),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportOut:
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(413, detail={"code": "too_large", "row": None})
    try:
        rows = importer.parse_csv(data)
    except importer.ImportError_ as error:
        raise _fail(422, error)
    return _run(
        db, settings, session, rows,
        label=file.filename or "import.csv", source="csv_import",
        bank_code=bank_code or None, account_number=account_number, opening_balance=opening_balance,
    )


@router.post("/manual", response_model=ImportOut, status_code=201)
def import_manual(
    body: ManualIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportOut:
    rows = [
        importer.Row(r.date, r.description.strip(), r.debit.quantize(Decimal("0.01")), r.credit.quantize(Decimal("0.01")),
                     None if r.balance is None else r.balance.quantize(Decimal("0.01")))
        for r in body.rows
    ]
    return _run(
        db, settings, session, rows,
        label="Typed by hand", source="manual_entry",
        bank_code=body.bank_code or None, account_number=body.account_number,
        opening_balance=body.opening_balance.quantize(Decimal("0.01")) if body.opening_balance is not None else None,
    )
