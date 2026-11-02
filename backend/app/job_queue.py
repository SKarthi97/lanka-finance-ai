"""Postgres-backed job queue (no Redis).

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED so several workers never take the
same job. The claim is committed immediately, so the job runs outside the lock;
a crashed worker's job is recovered after `stale_after_s`.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Job, utcnow

RETRY_BASE_S = 5


def enqueue(
    db: Session,
    job_type: str,
    document_id: int | None = None,
    payload: dict | None = None,
    max_attempts: int = 3,
) -> Job:
    """Add a job to the current transaction. The caller commits."""
    job = Job(
        type=job_type,
        document_id=document_id,
        payload=payload,
        max_attempts=max_attempts,
    )
    db.add(job)
    return job


def claim_next(db: Session, worker_id: str, stale_after_s: int = 600) -> Job | None:
    now = utcnow()
    stale_before = now - timedelta(seconds=stale_after_s)

    # Recover jobs whose worker disappeared: fail them if out of attempts, else requeue.
    db.execute(
        update(Job)
        .where(
            Job.status == "running",
            Job.locked_at < stale_before,
            Job.attempts >= Job.max_attempts,
        )
        .values(
            status="failed",
            last_error="Worker stopped responding",
            finished_at=now,
            locked_by=None,
        )
    )
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < stale_before)
        .values(status="queued", locked_by=None, locked_at=None)
    )

    job = db.scalar(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.commit()
        return None

    job.status = "running"
    job.attempts += 1
    job.locked_at = now
    job.locked_by = worker_id
    db.commit()
    return job


def complete(db: Session, job: Job) -> None:
    job.status = "done"
    job.finished_at = utcnow()
    job.locked_at = None
    job.locked_by = None
    job.last_error = None
    db.commit()


def fail(db: Session, job: Job, error: Exception) -> bool:
    """Record a failure. Returns True when the job is permanently failed."""
    now = utcnow()
    job.last_error = f"{type(error).__name__}: {error}"[:500]
    job.locked_at = None
    job.locked_by = None

    permanent = job.attempts >= job.max_attempts
    if permanent:
        job.status = "failed"
        job.finished_at = now
    else:
        job.status = "queued"
        job.run_after = now + timedelta(seconds=RETRY_BASE_S * 2 ** (job.attempts - 1))

    db.commit()
    return permanent
