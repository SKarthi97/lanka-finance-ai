from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Account, Bank, Transaction, UserSession

router = APIRouter(prefix="/api", tags=["transactions"])

MAX_PAGE_SIZE = 500


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


class TransactionList(BaseModel):
    total: int
    items: list[TransactionOut]


@router.get("/transactions", response_model=TransactionList)
def list_transactions(
    document_id: int | None = None,
    bank_code: str | None = Query(default=None, max_length=32),
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    validation_status: str | None = None,
    flagged: bool = False,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> TransactionList:
    conditions = [Transaction.user_id == session.user_id]
    if document_id is not None:
        conditions.append(Transaction.document_id == document_id)
    if bank_code:
        conditions.append(Bank.code == bank_code)
    if year is not None:
        # A month only makes sense within a year.
        start = date(year, month or 1, 1)
        if month is None:
            end = date(year + 1, 1, 1)
        else:
            end = date(year + (month == 12), month % 12 + 1, 1)
        conditions += [Transaction.transaction_date >= start, Transaction.transaction_date < end]
    if validation_status:
        conditions.append(Transaction.validation_status == validation_status)
    if flagged:  # any row that did not pass every check
        conditions.append(Transaction.validation_status != "ok")
    if q:
        conditions.append(Transaction.original_description.ilike(f"%{q.strip()}%"))

    joined = (
        select(Transaction, Bank.code, Bank.name, Account.account_number_last4)
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .outerjoin(Account, Transaction.account_id == Account.id)
        .where(*conditions)
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
        joined.order_by(
            Transaction.transaction_date.desc(),
            Transaction.document_id.desc(),
            Transaction.seq.desc(),
        )
        .limit(limit)
        .offset(offset)
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
            )
            for t, bank_code_, bank_name, last4 in rows
        ],
    )
