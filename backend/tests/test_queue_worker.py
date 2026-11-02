from datetime import timedelta

from sqlalchemy import select

from app import job_queue
from app.models import Document, DocumentPage, Job, User, utcnow
from app.services.inspection import classify_page
from app.worker import HANDLERS, process_one

from .conftest import make_pdf


def _enqueue(db, **kwargs):
    job = job_queue.enqueue(db, "noop", **kwargs)
    db.commit()
    return job


# --- queue ---------------------------------------------------------------


def test_claim_returns_oldest_and_marks_running(session_factory):
    with session_factory() as db:
        first = _enqueue(db)
        second = _enqueue(db)

        claimed = job_queue.claim_next(db, "w1")
        assert claimed.id == first.id
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.locked_by == "w1"

        # A second claim must not hand out the same job.
        assert job_queue.claim_next(db, "w2").id == second.id
        assert job_queue.claim_next(db, "w3") is None


def test_future_jobs_are_not_claimed(session_factory):
    with session_factory() as db:
        job = _enqueue(db)
        job.run_after = utcnow() + timedelta(hours=1)
        db.commit()
        assert job_queue.claim_next(db, "w1") is None


def test_failure_retries_with_backoff_then_gives_up(session_factory):
    with session_factory() as db:
        _enqueue(db, max_attempts=2)

        job = job_queue.claim_next(db, "w1")
        assert job_queue.fail(db, job, RuntimeError("boom")) is False
        assert job.status == "queued"
        assert job.run_after > utcnow()
        assert job.last_error == "RuntimeError: boom"

        job.run_after = utcnow()  # skip the backoff wait
        db.commit()

        job = job_queue.claim_next(db, "w1")
        assert job.attempts == 2
        assert job_queue.fail(db, job, RuntimeError("boom")) is True
        assert job.status == "failed"
        assert job.finished_at is not None


def test_stale_running_job_is_requeued(session_factory):
    with session_factory() as db:
        _enqueue(db)
        job = job_queue.claim_next(db, "crashed-worker")
        job.locked_at = utcnow() - timedelta(hours=1)
        db.commit()

        recovered = job_queue.claim_next(db, "w2", stale_after_s=60)
        assert recovered.id == job.id
        assert recovered.locked_by == "w2"
        assert recovered.attempts == 2


def test_stale_job_out_of_attempts_is_failed_not_retried(session_factory):
    with session_factory() as db:
        _enqueue(db, max_attempts=1)
        job = job_queue.claim_next(db, "crashed-worker")
        job.locked_at = utcnow() - timedelta(hours=1)
        db.commit()

        assert job_queue.claim_next(db, "w2", stale_after_s=60) is None
        db.refresh(job)
        assert job.status == "failed"


# --- page classification -------------------------------------------------


def test_classify_page():
    assert classify_page(500, 0) == "text"
    assert classify_page(500, 2) == "mixed"
    assert classify_page(0, 1) == "scanned"
    assert classify_page(5, 1) == "scanned"
    assert classify_page(0, 0) == "empty"


# --- worker --------------------------------------------------------------


def _document_with_file(db, settings, pdf_bytes, name="doc"):
    from app import storage

    user = db.scalar(select(User)) or User(username="owner", password_hash="x")
    db.add(user)
    db.flush()

    sha = (name * 64)[:64]
    relpath = storage.document_relpath(user.id, sha)
    storage.save_document(settings, relpath, pdf_bytes)

    document = Document(
        user_id=user.id,
        sha256=sha,
        storage_path=relpath,
        original_filename=f"{name}.pdf",
        size_bytes=len(pdf_bytes),
    )
    db.add(document)
    db.flush()
    job_queue.enqueue(db, "inspect_document", document_id=document.id, max_attempts=2)
    db.commit()
    return document


def test_worker_inspects_document_and_classifies_pages(session_factory, test_settings):
    with session_factory() as db:
        document = _document_with_file(
            db, test_settings, make_pdf(["Statement text " * 10, ""])
        )
        doc_id = document.id

    assert process_one(session_factory, "w1", test_settings) is True

    with session_factory() as db:
        document = db.get(Document, doc_id)
        assert document.status == "inspected"
        assert document.page_count == 2

        pages = db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == doc_id)
            .order_by(DocumentPage.page_no)
        ).all()
        assert [p.kind for p in pages] == ["text", "empty"]

        job = db.scalar(select(Job))
        assert job.status == "done"

    assert process_one(session_factory, "w1", test_settings) is False  # queue drained


def test_worker_marks_document_failed_after_final_attempt(session_factory, test_settings):
    with session_factory() as db:
        document = _document_with_file(db, test_settings, b"%PDF-1.7 not a real pdf")
        doc_id = document.id

    assert process_one(session_factory, "w1", test_settings) is True

    with session_factory() as db:
        job = db.scalar(select(Job))
        assert job.status == "queued"  # first attempt failed, will retry
        assert db.get(Document, doc_id).status == "processing"
        job.run_after = utcnow()
        db.commit()

    assert process_one(session_factory, "w1", test_settings) is True

    with session_factory() as db:
        job = db.scalar(select(Job))
        document = db.get(Document, doc_id)
        assert job.status == "failed"
        assert document.status == "failed"
        assert document.error


def test_unknown_job_type_fails_cleanly(session_factory, test_settings):
    with session_factory() as db:
        _enqueue(db, max_attempts=1)  # type "noop" has no handler

    assert "noop" not in HANDLERS
    assert process_one(session_factory, "w1", test_settings) is True

    with session_factory() as db:
        job = db.scalar(select(Job))
        assert job.status == "failed"
        assert "Unknown job type" in job.last_error


# --- retention -------------------------------------------------------------


def _run_inspection(session_factory, settings, pdf_bytes):
    from app import storage

    with session_factory() as db:
        document = _document_with_file(db, settings, pdf_bytes)
        doc_id, relpath = document.id, document.storage_path

    process_one(session_factory, "w1", settings)
    return doc_id, storage.resolve(settings, relpath)


def test_file_is_deleted_after_successful_processing(session_factory, test_settings):
    assert test_settings.retain_documents is False

    doc_id, path = _run_inspection(session_factory, test_settings, make_pdf())

    assert not path.exists()
    with session_factory() as db:
        document = db.get(Document, doc_id)
        assert document.status == "inspected"
        assert document.file_deleted_at is not None
        assert document.sha256  # kept, so duplicate detection still works


def test_file_is_kept_when_retention_is_on(session_factory, test_settings):
    test_settings.retain_documents = True

    doc_id, path = _run_inspection(session_factory, test_settings, make_pdf())

    assert path.exists()
    with session_factory() as db:
        assert db.get(Document, doc_id).file_deleted_at is None


def test_file_is_kept_when_processing_fails(session_factory, test_settings):
    doc_id, path = _run_inspection(
        session_factory, test_settings, b"%PDF-1.7 not a real pdf"
    )

    assert path.exists()  # still needed for a retry
    with session_factory() as db:
        assert db.get(Document, doc_id).file_deleted_at is None
