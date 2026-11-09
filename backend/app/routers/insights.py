import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import Category, Transaction, UserSession
from app.services import flags as flag_service
from app.services import summary

router = APIRouter(prefix="/api", tags=["insights"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


# --- 4.4 month summary -------------------------------------------------------------------------------


class SummaryIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    ai: bool = True  # False: only the plain summary written by code


class SummaryOut(BaseModel):
    label: str
    bullets: list[str]  # always present; written by code, with the real amounts
    narrative: str | None  # a friendly paragraph from the local AI, when it was asked and passed the checks
    used_ai: bool
    ai_note: str | None
    took_ms: int
    model_ms: int | None


@router.post("/summary", response_model=SummaryOut)
def month_summary(
    body: SummaryIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SummaryOut:
    """The month in sentences. The figures come from code; the AI only phrases a paragraph from
    facts that contain no amounts, and the paragraph is dropped if it adds a number."""
    began = time.perf_counter()
    facts = summary.compute_facts(db, session.user_id, body.year, body.month, today=date.today())
    narrative = model_ms = note = None
    if body.ai and facts.transactions > 0:
        narrative, model_ms, note = summary.narrate(db, settings, facts)
        db.commit()  # records the model call (a hash and a duration)
    return SummaryOut(
        label=facts.label,
        bullets=summary.bullets(facts),
        narrative=narrative,
        used_ai=narrative is not None,
        ai_note=note,
        took_ms=round((time.perf_counter() - began) * 1000),
        model_ms=model_ms,
    )


# --- 4.5 flagged transactions ---------------------------------------------------------------------------


class FlagOut(BaseModel):
    code: str
    title: str


class FlagsOut(BaseModel):
    flags: list[FlagOut]


class ExplainOut(BaseModel):
    flags: list[FlagOut]
    explanation: str | None
    check: str | None
    used_ai: bool
    ai_note: str | None
    took_ms: int
    model_ms: int | None


def _mine(db: Session, user_id: int, transaction_id: int) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != user_id:
        raise _error(404, "not_found", "Transaction not found.")
    return transaction


@router.get("/transactions/{transaction_id}/flags", response_model=FlagsOut)
def transaction_flags(
    transaction_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> FlagsOut:
    """Why this transaction is flagged, in fixed sentences from the app's own checks."""
    t = _mine(db, session.user_id, transaction_id)
    return FlagsOut(flags=[FlagOut(code=f.code, title=f.title) for f in flag_service.flags_for(db, session.user_id, t)])


@router.post("/transactions/{transaction_id}/explain", response_model=ExplainOut)
def explain_transaction(
    transaction_id: int,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExplainOut:
    """Ask the local AI to put the reasons in plain words. It sees the reasons, the money
    direction and the category name; not the description, amount, date or account."""
    began = time.perf_counter()
    t = _mine(db, session.user_id, transaction_id)
    found = flag_service.flags_for(db, session.user_id, t)
    if not found:
        raise _error(409, "nothing_flagged", "Nothing unusual was found about this transaction.")
    category = db.get(Category, t.category_id) if t.category_id else None
    reply, model_ms, note = flag_service.explain(db, settings, t, found, category.name if category else None)
    db.commit()
    return ExplainOut(
        flags=[FlagOut(code=f.code, title=f.title) for f in found],
        explanation=reply.explanation if reply else None,
        check=reply.check if reply else None,
        used_ai=reply is not None,
        ai_note=note,
        took_ms=round((time.perf_counter() - began) * 1000),
        model_ms=model_ms,
    )
