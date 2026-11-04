"""Background worker: python -m app.worker

Polls the Postgres job queue. Runs in its own container with no published ports.
"""

import logging
import os
import signal
import socket
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app import job_queue as queue
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import Document, Job
from app.services.categorizer import classify_all_users
from app.services.dedupe import refresh_all_users
from app.services.extraction import extract_transactions
from app.services.inspection import inspect_document
from app.services.llm_classifier import JOB_TYPE as CLASSIFY_JOB, run_classify_job
from app.services.merchants import JOB_TYPE as NAMING_JOB, run_naming_job

log = logging.getLogger("worker")

Handler = Callable[[Session, Job, Settings], None]

HANDLERS: dict[str, Handler] = {
    "inspect_document": inspect_document,
    "extract_transactions": extract_transactions,
    CLASSIFY_JOB: run_classify_job,
    NAMING_JOB: run_naming_job,
}

# Only these jobs decide a statement's status. A failed AI pass must never fail a statement.
STATEMENT_JOBS = {"inspect_document", "extract_transactions"}


def process_one(
    session_factory: sessionmaker, worker_id: str, settings: Settings
) -> bool:
    """Claim and run one job. Returns False when the queue is empty."""
    with session_factory() as db:
        job = queue.claim_next(db, worker_id, settings.job_stale_after_s)
        if job is None:
            return False

        # Log ids and types only, never document content.
        log.info("job %s (%s) started, attempt %s", job.id, job.type, job.attempts)

        try:
            handler = HANDLERS.get(job.type)
            if handler is None:
                raise ValueError(f"Unknown job type: {job.type}")
            handler(db, job, settings)
            queue.complete(db, job)
            log.info("job %s done", job.id)
        except Exception as error:  # noqa: BLE001 - any handler failure is recorded
            db.rollback()
            permanent = queue.fail(db, job, error)
            log.warning(
                "job %s failed (%s), %s",
                job.id,
                type(error).__name__,
                "giving up" if permanent else "will retry",
            )
            if permanent and job.document_id and job.type in STATEMENT_JOBS:
                document = db.get(Document, job.document_id)
                if document is not None:
                    document.status = "failed"
                    document.error = job.last_error
                    db.commit()
        return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"

    stopping = False

    def request_stop(signum, frame):  # noqa: ARG001
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    # Flag duplicates among rows that predate the duplicate columns. Idempotent.
    try:
        with SessionLocal() as db:
            log.info("duplicate backfill: %s duplicate rows", refresh_all_users(db))
    except Exception:  # noqa: BLE001 - never stop the worker over a maintenance task
        log.exception("duplicate backfill failed")

    # Categorise rows saved before categories existed. Idempotent.
    try:
        with SessionLocal() as db:
            log.info("categorisation backfill: %s rows updated", classify_all_users(db))
    except Exception:  # noqa: BLE001
        log.exception("categorisation backfill failed")

    log.info("worker %s started", worker_id)
    while not stopping:
        try:
            if process_one(SessionLocal, worker_id, settings):
                continue  # drain the queue before sleeping
        except Exception:  # noqa: BLE001 - e.g. database briefly unavailable
            log.exception("worker loop error")
        time.sleep(settings.job_poll_s)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
