from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Document, Transaction, TransferRejection, UserSession
from app.services import categorizer, transfers
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class SideOut(BaseModel):
    id: int
    transaction_date: date
    description: str
    bank_code: str | None
    account_last4: str | None


class PairOut(BaseModel):
    out: SideOut  # money leaving
    into: SideOut  # money arriving
    amount: Decimal
    days_apart: int
    ambiguous: bool


class SuggestionsOut(BaseModel):
    total: int
    window_days: int
    items: list[PairOut]


class PairIn(BaseModel):
    out_id: int
    in_id: int


class ConfirmOut(BaseModel):
    category_name: str


def _side_out(side: transfers.Side) -> SideOut:
    return SideOut(
        id=side.id,
        transaction_date=side.date,
        description=side.description,
        bank_code=side.bank_code,
        account_last4=side.account_last4,
    )


@router.get("/suggestions", response_model=SuggestionsOut)
def suggestions(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> SuggestionsOut:
    pairs = transfers.find_pairs(db, session.user_id)
    return SuggestionsOut(
        total=len(pairs),
        window_days=transfers.WINDOW_DAYS,
        items=[
            PairOut(
                out=_side_out(p.out),
                into=_side_out(p.into),
                amount=p.out.amount,
                days_apart=p.days_apart,
                ambiguous=p.ambiguous,
            )
            for p in pairs
        ],
    )


def _load_pair(db: Session, user_id: int, body: PairIn) -> tuple[Transaction, Transaction]:
    """Both rows must be yours, counted in analytics, and really be the two halves of a
    transfer (a debit and a credit of one amount in different accounts)."""
    out = db.get(Transaction, body.out_id)
    incoming = db.get(Transaction, body.in_id)
    if out is None or incoming is None or out.user_id != user_id or incoming.user_id != user_id:
        raise _error(404, "not_found", "Transaction not found.")
    statuses = dict(
        db.execute(
            select(Document.id, Document.status).where(
                Document.id.in_({out.document_id, incoming.document_id})
            )
        ).all()
    )
    if any(statuses.get(t.document_id) not in ACTIVE_STATUSES for t in (out, incoming)):
        raise _error(409, "not_counted", "Both statements must be reconciled or accepted.")
    if not (out.debit > 0 and incoming.credit > 0 and out.debit == incoming.credit):
        raise _error(422, "not_a_pair", "These are not a debit and a credit of the same amount.")
    if (out.bank_id, out.account_id) == (incoming.bank_id, incoming.account_id):
        raise _error(422, "same_account", "Both rows are in the same account.")
    return out, incoming


@router.post("/confirm", response_model=ConfirmOut)
def confirm(
    body: PairIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ConfirmOut:
    """File both halves under the transfer category, as if you had set it yourself. No rule
    is learned from this: a description alone does not make something a transfer."""
    out, incoming = _load_pair(db, session.user_id, body)
    category = transfers.transfer_category(db, session.user_id)
    if category is None:
        raise _error(409, "no_transfer_category", "Create a category of kind Transfer first.")
    for row in (out, incoming):
        categorizer.set_manual_category(db, session.user_id, row, category.id)
    db.commit()
    return ConfirmOut(category_name=category.name)


@router.post("/reject", status_code=204)
def reject(
    body: PairIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    out, incoming = _load_pair(db, session.user_id, body)
    first, second = transfers.pair_key(out.row_hash, incoming.row_hash)
    exists = db.scalar(
        select(TransferRejection.id).where(
            TransferRejection.user_id == session.user_id,
            TransferRejection.hash_a == first,
            TransferRejection.hash_b == second,
        )
    )
    if exists is None:
        db.add(TransferRejection(user_id=session.user_id, hash_a=first, hash_b=second))
        db.commit()
