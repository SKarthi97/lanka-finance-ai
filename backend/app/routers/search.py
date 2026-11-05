import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.routers.views import ViewFilters
from app.services import search

router = APIRouter(prefix="/api/search", tags=["search"])


class InterpretIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class InterpretOut(BaseModel):
    filters: ViewFilters
    summary: list[str]  # the filters in words, so you can check them
    used_ai: bool
    ai_error: str | None
    took_ms: int  # the whole question, start to finish
    model_ms: int | None  # of which waiting for the local model (None: it was not asked)


@router.post("/interpret", response_model=InterpretOut)
def interpret(
    body: InterpretIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InterpretOut:
    """Read a typed question as Transactions filters. Returns filters only; nothing is run or
    changed. The text goes to the local model only (never to the internet), and only the words
    left after dates, amounts, banks and categories were read by code."""
    began = time.perf_counter()
    reading = search.interpret(db, settings, session.user_id, body.query)
    db.commit()  # records the model call (a hash, never the text)
    return InterpretOut(
        filters=ViewFilters(**reading.filters),
        summary=reading.summary,
        used_ai=reading.used_ai,
        ai_error=reading.ai_error,
        took_ms=round((time.perf_counter() - began) * 1000),
        model_ms=reading.model_ms,
    )
