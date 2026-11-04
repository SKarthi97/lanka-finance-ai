from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import Transaction, UserSession
from app.services import merchants
from app.services.categorizer import description_stem

router = APIRouter(prefix="/api", tags=["merchants"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=merchants.MAX_NAME_LENGTH)


class NameOut(BaseModel):
    merchant: str
    merchant_source: str


def _stem_of(db: Session, user_id: int, transaction_id: int) -> str:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != user_id:
        raise _error(404, "not_found", "Transaction not found.")
    stem = description_stem(transaction.original_description)
    if not stem:
        raise _error(422, "no_stem", "This description has no reusable part to name.")
    return stem


@router.put("/transactions/{transaction_id}/merchant", response_model=NameOut)
def rename_merchant(
    transaction_id: int,
    body: NameIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> NameOut:
    """Name this merchant yourself. Every transaction with the same description stem, now and
    on future statements, shows the name. It is never overwritten by the model."""
    name = " ".join(body.name.split())
    if not name:
        raise _error(422, "name_required", "Enter a name.")
    stem = _stem_of(db, session.user_id, transaction_id)
    merchants.set_manual(db, session.user_id, stem, name)
    db.commit()
    return NameOut(merchant=name, merchant_source="manual")


@router.delete("/transactions/{transaction_id}/merchant", response_model=NameOut)
def reset_merchant(
    transaction_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> NameOut:
    """Forget the stored name; the tidied description is shown again (and the model may
    propose a name on its next pass)."""
    stem = _stem_of(db, session.user_id, transaction_id)
    merchants.clear(db, session.user_id, stem)
    db.commit()
    return NameOut(merchant=merchants.rule_clean(stem), merchant_source="rule")


class QueuedOut(BaseModel):
    queued: bool


@router.post("/merchants/name", response_model=QueuedOut, status_code=202)
def name_merchants(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QueuedOut:
    """Ask the local model to propose names for merchants that have none yet."""
    queued = merchants.enqueue_naming(db, settings, session.user_id)
    db.commit()
    return QueuedOut(queued=queued)
