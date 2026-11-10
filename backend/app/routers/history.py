"""What happened to one transaction: where it was read from and every change you made to it."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import AuditLog, Category, ClassificationFeedback, Document, Transaction, UserSession

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

SOURCE_WORDS = {
    "manual": "set by you",
    "rule": "by a rule",
    "builtin": "by a built-in rule",
    "correction": "by a rule learned from your correction",
    "llm": "suggested by the local AI",
    "embedding": "suggested from similar descriptions",
}


class Event(BaseModel):
    at: datetime
    kind: str  # read | category | merchant
    text: str


class HistoryOut(BaseModel):
    current: str  # the state now, in words
    events: list[Event]  # newest first


@router.get("/{transaction_id}/history", response_model=HistoryOut)
def history(
    transaction_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HistoryOut:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != session.user_id:
        raise HTTPException(404, detail={"code": "not_found", "message": "Transaction not found."})

    names = {c.id: c.name for c in db.scalars(select(Category).where(Category.user_id == session.user_id))}
    name = lambda cid: names.get(cid, "Uncategorised") if cid is not None else "Uncategorised"  # noqa: E731

    events: list[Event] = []
    document = db.get(Document, transaction.document_id)
    if document is not None:
        how = "imported" if document.adapter == "import" else f"read by the {document.adapter or 'statement'} reader"
        events.append(Event(at=document.created_at, kind="read", text=f"Added from “{document.original_filename}” ({how})."))

    for row in db.scalars(
        select(ClassificationFeedback).where(
            ClassificationFeedback.user_id == session.user_id, ClassificationFeedback.transaction_id == transaction.id
        )
    ):
        events.append(
            Event(at=row.at, kind="category", text=f"You changed the category from {name(row.from_category_id)} to {name(row.to_category_id)}.")
        )

    for row in db.scalars(
        select(AuditLog).where(
            AuditLog.user_id == session.user_id,
            AuditLog.entity == "transaction",
            AuditLog.entity_id == str(transaction.id),
        )
    ):
        detail = row.detail or {}
        if row.action == "transaction.merchant_rename":
            events.append(Event(at=row.at, kind="merchant", text=f"You named the merchant “{detail.get('name', '')}”."))
        elif row.action == "transaction.merchant_reset":
            events.append(Event(at=row.at, kind="merchant", text="You cleared the merchant name."))

    events.sort(key=lambda e: e.at, reverse=True)
    source = SOURCE_WORDS.get(transaction.classification_source or "", "")
    current = f"Category: {name(transaction.category_id)}" + (f", {source}" if source and transaction.category_id else "") + "."
    if transaction.classification_explanation and transaction.classification_source != "manual":
        current += f" {transaction.classification_explanation}"
    return HistoryOut(current=current, events=events)
