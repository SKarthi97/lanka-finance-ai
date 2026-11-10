from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import StemEmbedding, UserSession
from app.services import ai_activity, embeddings

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


class SimilarityOut(BaseModel):
    enabled: bool  # EMBED_SUGGEST_ENABLED
    model: str
    labelled: int  # descriptions you categorised yourself
    needed: int  # the fewest labels before hints are offered
    embedded: int  # vectors cached for this model


@router.get("/similarity", response_model=SimilarityOut)
def similarity(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SimilarityOut:
    """State of the "like ones you chose" hints (off until you have measured them)."""
    embedded = db.scalar(
        select(func.count())
        .select_from(StemEmbedding)
        .where(StemEmbedding.user_id == session.user_id, StemEmbedding.model == embeddings.cache_key(settings))
    )
    return SimilarityOut(
        enabled=settings.embed_enabled,
        model=settings.ollama_embed_model,
        labelled=len(embeddings.labelled_stems(db, session.user_id)),
        needed=settings.embed_min_labelled,
        embedded=embedded or 0,
    )
