"""What the local model is doing and how long it takes, for the progress displays.

Nothing here touches prompts or replies: `model_runs` holds only the purpose, model, duration
and whether the reply was valid JSON (never the text, not even a readable form of it). From
those durations come an honest estimate ("usually about 2 min") and the activity list on the
System page.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Job, MerchantName, ModelRun, Transaction
from app.services.categorizer import description_stem

CALL_HISTORY = 30  # recent calls used for the average
ACTIVITY_DAYS = 30


@dataclass
class Progress:
    running: bool = False  # a worker has the job right now
    queued: bool = False  # waiting for a worker
    elapsed_s: int | None = None  # since the job started (or was queued)
    eta_s: int | None = None  # whole job, from average call time; None with no history yet
    waiting: int = 0  # distinct descriptions the job would cover
    avg_call_s: float | None = None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def avg_call_ms(db: Session, purpose: str) -> int | None:
    """Mean duration of the most recent valid calls for a purpose."""
    recent = db.scalars(
        select(ModelRun.duration_ms)
        .where(ModelRun.purpose == purpose, ModelRun.valid_json.is_(True))
        .order_by(ModelRun.id.desc())
        .limit(CALL_HISTORY)
    ).all()
    return round(sum(recent) / len(recent)) if recent else None


def progress(
    db: Session,
    user_id: int,
    job_type: str,
    purpose: str,
    waiting: int,
    batch_size: int,
    cap: int,
    now: datetime | None = None,
) -> Progress:
    now = now or datetime.now(UTC)
    result = Progress(waiting=waiting)
    average = avg_call_ms(db, purpose)
    if average is not None:
        result.avg_call_s = round(average / 1000, 1)
        calls = math.ceil(min(waiting, cap) / batch_size) if waiting else 0
        result.eta_s = round(calls * average / 1000) if calls else None

    job = next(
        (
            j
            for j in db.scalars(
                select(Job).where(Job.type == job_type, Job.status.in_(("queued", "running")))
            )
            if (j.payload or {}).get("user_id") == user_id
        ),
        None,
    )
    if job is None:
        return result
    result.running = job.status == "running"
    result.queued = not result.running
    started = _aware(job.locked_at or job.created_at)
    result.elapsed_s = max(0, int((now - started).total_seconds()))
    return result


def categorise_waiting(db: Session, user_id: int) -> int:
    """Distinct descriptions (by stem) the AI categoriser would look at."""
    stems = {
        description_stem(d)
        for (d,) in db.execute(
            select(Transaction.original_description)
            .where(
                Transaction.user_id == user_id,
                Transaction.category_id.is_(None),
                Transaction.classification_source.is_(None),
            )
            .distinct()
        )
    }
    stems.discard("")
    return len(stems)


def naming_waiting(db: Session, user_id: int) -> int:
    """Distinct stems with no stored merchant name yet."""
    have = set(db.scalars(select(MerchantName.stem).where(MerchantName.user_id == user_id)))
    stems = {
        description_stem(d)
        for (d,) in db.execute(
            select(Transaction.original_description)
            .where(Transaction.user_id == user_id)
            .distinct()
        )
    }
    stems.discard("")
    return len(stems - have)


# --- the activity list ---------------------------------------------------------------------------


@dataclass
class PurposeSummary:
    purpose: str
    runs: int
    ok_runs: int
    avg_ms: int
    max_ms: int
    total_ms: int


def summary(db: Session, now: datetime | None = None) -> list[PurposeSummary]:
    since = (now or datetime.now(UTC)) - timedelta(days=ACTIVITY_DAYS)
    rows = db.execute(
        select(
            ModelRun.purpose,
            func.count(),
            func.sum(case((ModelRun.valid_json.is_(True), 1), else_=0)),
            func.avg(ModelRun.duration_ms),
            func.max(ModelRun.duration_ms),
            func.sum(ModelRun.duration_ms),
        )
        .where(ModelRun.at >= since)
        .group_by(ModelRun.purpose)
        .order_by(ModelRun.purpose)
    ).all()
    return [
        PurposeSummary(
            purpose=purpose,
            runs=runs,
            ok_runs=int(ok or 0),
            avg_ms=round(avg or 0),
            max_ms=int(biggest or 0),
            total_ms=int(total or 0),
        )
        for purpose, runs, ok, avg, biggest, total in rows
    ]


def recent(db: Session, limit: int = 30) -> list[ModelRun]:
    return list(db.scalars(select(ModelRun).order_by(ModelRun.id.desc()).limit(limit)))
