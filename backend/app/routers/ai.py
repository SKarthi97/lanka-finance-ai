from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import ai_activity

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ProgressOut(BaseModel):
    """Where a background AI job stands. `eta_s` is the whole job's usual duration from the
    average recent call, not a promise."""

    running: bool
    queued: bool
    elapsed_s: int | None
    eta_s: int | None
    waiting: int
    avg_call_s: float | None


def progress_out(p: ai_activity.Progress) -> ProgressOut:
    return ProgressOut(**vars(p))


class PurposeOut(BaseModel):
    purpose: str  # categorize | merchant | search
    runs: int
    ok_runs: int  # replies that were valid JSON
    avg_ms: int
    max_ms: int
    total_ms: int


class RunOut(BaseModel):
    at: datetime
    purpose: str
    model: str
    duration_ms: int
    ok: bool


class ActivityOut(BaseModel):
    window_days: int
    summary: list[PurposeOut]
    recent: list[RunOut]


@router.get("/activity", response_model=ActivityOut)
def activity(
    _: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> ActivityOut:
    """How often the local model was called and how long it took. Durations and outcomes only:
    prompts and replies are never stored."""
    return ActivityOut(
        window_days=ai_activity.ACTIVITY_DAYS,
        summary=[PurposeOut(**vars(s)) for s in ai_activity.summary(db)],
        recent=[
            RunOut(at=r.at, purpose=r.purpose, model=r.model, duration_ms=r.duration_ms, ok=r.valid_json)
            for r in ai_activity.recent(db)
        ],
    )
