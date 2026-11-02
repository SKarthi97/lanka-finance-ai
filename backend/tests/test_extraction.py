import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Account, Document, Job, Transaction
from app.worker import process_one

from .conftest import make_pdf
from .synthetic import FAKE_ACCOUNT, boc_pdf, upload


def run_pipeline(client, csrf, session_factory, settings, pdf, **form):
    """Upload, then run the inspection and extraction jobs through the real worker."""
    response = upload(client, csrf, pdf, **form)
    assert response.status_code == 202, response.text
    for _ in range(2):  # inspect_document, then extract_transactions
        assert process_one(session_factory, "w1", settings) is True
    return response.json()["id"]


def stored_path(settings, doc: Document) -> Path:
    return Path(settings.documents_dir) / doc.storage_path


def test_reconciled_statement_is_extracted_and_file_removed(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(), bank_code="boc"
    )

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.adapter == "boc"
        assert doc.opening_balance == Decimal("1000.00")
        assert doc.closing_balance == Decimal("900.00")
        assert doc.period_start == date(2022, 8, 30)
        assert doc.period_end == date(2022, 9, 30)
        assert doc.extraction_confidence == 1.0
        assert doc.validation["reconciled"] is True
        assert doc.page_count == 1

        (tx,) = db.scalars(select(Transaction)).all()
        assert tx.original_description == "ATM CASH WITHDRAWAL"
        assert tx.debit == Decimal("100.00")
        assert tx.credit == Decimal("0.00")
        assert tx.running_balance == Decimal("900.00")
        assert tx.source_page == 1
        assert tx.validation_status == "ok"
        assert len(tx.row_hash) == 64

        # default retention: the plain PDF is gone once reconciled
        assert doc.file_deleted_at is not None
        assert not stored_path(test_settings, doc).exists()


def test_bank_is_detected_when_not_chosen(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, boc_pdf())

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.bank.code == "boc"


def test_retention_on_keeps_the_file(logged_in, session_factory, test_settings):
    test_settings.retain_documents = True
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, boc_pdf())

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.file_deleted_at is None
        assert stored_path(test_settings, doc).exists()


def test_failed_reconciliation_goes_to_review_and_keeps_file(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(closing="999.00")
    )

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "needs_review"
        assert doc.file_deleted_at is None  # needed for review
        assert stored_path(test_settings, doc).exists()
        codes = [i["code"] for i in doc.validation["issues"]]
        assert "statement_not_reconciled" in codes
        assert doc.extraction_confidence <= 0.5
        assert len(db.scalars(select(Transaction)).all()) == 1  # kept, flagged by status


def test_unrecognised_layout_fails_once_without_retries(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    response = upload(client, csrf, make_pdf(["Some other bank statement " * 6]))
    assert response.status_code == 202

    process_one(session_factory, "w1", test_settings)  # inspect
    process_one(session_factory, "w1", test_settings)  # extract

    with session_factory() as db:
        doc = db.scalar(select(Document))
        job = db.scalar(select(Job).where(Job.type == "extract_transactions"))
        assert doc.status == "failed"
        assert "unsupported_layout" in doc.error
        assert (job.status, job.attempts) == ("failed", 1)  # not retried
        assert stored_path(test_settings, doc).exists()  # kept for retry


def test_chosen_bank_with_other_layout_reports_format_mismatch(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    upload_response = upload(
        client, csrf, make_pdf(["DATE: 30/09/2022 plain text " * 4]), bank_code="boc"
    )
    assert upload_response.status_code == 202
    process_one(session_factory, "w1", test_settings)
    process_one(session_factory, "w1", test_settings)

    with session_factory() as db:
        assert "format_mismatch" in db.scalar(select(Document)).error


def test_pdf_without_text_layer_reports_no_text(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    upload(client, csrf, make_pdf([""]))
    process_one(session_factory, "w1", test_settings)
    process_one(session_factory, "w1", test_settings)

    with session_factory() as db:
        assert "no_text_layer" in db.scalar(select(Document)).error


def test_reprocessing_is_idempotent(logged_in, session_factory, test_settings):
    test_settings.retain_documents = True
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, boc_pdf())

    from app.job_queue import enqueue

    with session_factory() as db:
        enqueue(db, "extract_transactions", document_id=doc_id)
        db.commit()
    process_one(session_factory, "w1", test_settings)

    with session_factory() as db:
        assert len(db.scalars(select(Transaction)).all()) == 1


# --- privacy -----------------------------------------------------------------


def test_full_account_number_is_never_stored_or_logged(
    logged_in, session_factory, test_settings, caplog
):
    caplog.set_level(logging.DEBUG)
    client, csrf = logged_in
    run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(account=FAKE_ACCOUNT)
    )

    with session_factory() as db:
        (account,) = db.scalars(select(Account)).all()
        assert account.account_number_last4 == FAKE_ACCOUNT[-4:]
        assert len(account.account_fingerprint) == 64
        assert db.scalar(select(Document)).account_id == account.id

    # Nothing in the whole database contains the number, in any table.
    engine = session_factory.kw["bind"]
    with engine.connect() as connection:
        dump = "\n".join(connection.connection.driver_connection.iterdump())
    assert FAKE_ACCOUNT not in dump

    # Nor do the logs contain it, or any statement text or amounts.
    for secret in (FAKE_ACCOUNT, "ATM CASH WITHDRAWAL", "100.00", "900.00"):
        assert secret not in caplog.text


def test_same_account_across_statements_shares_one_account_row(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(account=FAKE_ACCOUNT))
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            account=FAKE_ACCOUNT,
            statement_date="31/10/2022",
            opening=("30/09", "900.00"),
            rows=[("05/10", "POS PURCHASE SYNTHETIC", "50.00", "850.00")],
            closing="850.00",
        ),
    )

    with session_factory() as db:
        assert len(db.scalars(select(Account)).all()) == 1
        docs = db.scalars(select(Document).order_by(Document.id)).all()
        assert docs[0].account_id == docs[1].account_id
        # continuous statements raise no cross-statement warnings
        assert [i["code"] for i in docs[1].validation["issues"]] == []


@pytest.mark.parametrize(
    "opening, expected",
    [
        (("30/09", "800.00"), "opening_balance_gap"),  # does not start at 900.00
        (("15/09", "900.00"), "period_overlap"),  # starts before the previous ended
        (("15/10", "900.00"), "period_gap"),  # a gap after the previous ended
    ],
)
def test_cross_statement_continuity_is_reported(
    logged_in, session_factory, test_settings, opening, expected
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(account=FAKE_ACCOUNT))

    opening_balance = Decimal(opening[1])
    closing = opening_balance - Decimal("50.00")
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            account=FAKE_ACCOUNT,
            statement_date="31/10/2022",
            opening=opening,
            rows=[("20/10", "POS PURCHASE SYNTHETIC", "50.00", f"{closing}")],
            closing=f"{closing}",
        ),
    )

    with session_factory() as db:
        second = db.scalars(select(Document).order_by(Document.id)).all()[1]
        assert expected in [i["code"] for i in second.validation["issues"]]
