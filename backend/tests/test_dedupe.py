"""Overlapping statements must not double-count. All data is synthetic."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import Document, Transaction, User
from app.services.dedupe import refresh_all_users, refresh_duplicates

from .synthetic import boc_pdf
from .test_extraction import run_pipeline

TWO_ROWS = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
]


def september(**kwargs):
    """Sep 2022 only. 1,000 + 2,500 - 500 = 3,000."""
    return boc_pdf(rows=TWO_ROWS, closing="3,000.00", **kwargs)


def september_and_october(**kwargs):
    """Covers the same two September rows as `september`, plus one in October."""
    return boc_pdf(
        statement_date="31/10/2022",
        opening=("30/08", "1,000.00"),
        rows=TWO_ROWS + [("05/10", "POS PURCHASE SYNTHETIC", "50.00", "2,950.00")],
        closing="2,950.00",
        **kwargs,
    )


def rows(client, mode="show"):
    return client.get(f"/api/transactions?duplicates={mode}&limit=500").json()["items"]


def year_totals(client):
    year = client.get("/api/dashboard?year=2022&month=9").json()["year"]
    return Decimal(year["income"]), Decimal(year["expense"]), year["transactions"]


def test_overlapping_statements_are_not_double_counted(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    run_pipeline(client, csrf, session_factory, test_settings, september_and_october())

    assert len(rows(client, "show")) == 5  # everything stays visible
    assert len(rows(client, "hide")) == 3  # the explorer shows each transaction once

    income, expense, count = year_totals(client)
    assert income == Decimal("2500.00")  # not 5,000
    assert expense == Decimal("550.00")  # 500 + 50, not 1,050
    assert count == 3

    month = client.get("/api/dashboard?year=2022&month=9").json()["month"]
    assert Decimal(month["income"]) == Decimal("2500.00")
    assert month["transactions"] == 2


def test_earlier_upload_is_the_original_and_later_rows_point_at_it(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    first = run_pipeline(client, csrf, session_factory, test_settings, september())
    second = run_pipeline(client, csrf, session_factory, test_settings, september_and_october())

    duplicates = rows(client, "only")
    assert len(duplicates) == 2
    assert {t["document_id"] for t in duplicates} == {second}

    originals = {t["id"]: t for t in rows(client, "hide")}
    for duplicate in duplicates:
        original = originals[duplicate["duplicate_of_id"]]
        assert original["document_id"] == first
        assert original["description"] == duplicate["description"]
        assert original["is_duplicate"] is False

    assert client.get(f"/api/documents/{first}").json()["duplicate_count"] == 0
    assert client.get(f"/api/documents/{second}").json()["duplicate_count"] == 2


def test_upload_order_does_not_change_the_totals(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september_and_october())
    run_pipeline(client, csrf, session_factory, test_settings, september())

    assert year_totals(client) == (Decimal("2500.00"), Decimal("550.00"), 3)
    assert len(rows(client, "hide")) == 3


def test_a_statement_that_counts_beats_one_still_needing_review(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    headers = {"X-CSRF-Token": csrf}
    needs_review = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(rows=TWO_ROWS, closing="999.00")
    )
    reconciled = run_pipeline(
        client, csrf, session_factory, test_settings, september_and_october()
    )

    # The older upload needs review, so the reconciled statement holds the originals.
    assert {t["document_id"] for t in rows(client, "only")} == {needs_review}
    assert year_totals(client) == (Decimal("2500.00"), Decimal("550.00"), 3)

    # Accepting it makes both count equally; the earlier upload is then the original.
    assert (
        client.post(f"/api/documents/{needs_review}/accept", headers=headers).status_code == 200
    )
    assert {t["document_id"] for t in rows(client, "only")} == {reconciled}
    assert year_totals(client) == (Decimal("2500.00"), Decimal("550.00"), 3)  # unchanged


def test_deleting_the_original_promotes_the_duplicate(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    first = run_pipeline(client, csrf, session_factory, test_settings, september())
    run_pipeline(client, csrf, session_factory, test_settings, september_and_october())
    assert len(rows(client, "only")) == 2

    response = client.delete(f"/api/documents/{first}", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204

    assert rows(client, "only") == []  # nothing is a duplicate any more
    assert year_totals(client) == (Decimal("2500.00"), Decimal("550.00"), 3)  # still correct
    assert all(t["duplicate_of_id"] is None for t in rows(client))


def test_reprocessing_does_not_create_duplicates_of_itself(
    logged_in, session_factory, test_settings
):
    test_settings.retain_documents = True
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, september())

    from app.job_queue import enqueue
    from app.worker import process_one

    with session_factory() as db:
        enqueue(db, "extract_transactions", document_id=doc_id)
        db.commit()
    process_one(session_factory, "w1", test_settings)

    assert rows(client, "only") == []
    assert len(rows(client, "show")) == 2


# --- what must NOT be treated as a duplicate ------------------------------------------


def test_identical_looking_charges_with_different_balances_are_separate(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            opening=("30/08", "1,000.00"),
            rows=[
                ("05/09", "ATM SERVICE CHARGE", "5.00", "995.00"),
                ("05/09", "ATM SERVICE CHARGE", "5.00", "990.00"),  # same day, same text
            ],
            closing="990.00",
        ),
    )
    assert rows(client, "only") == []
    assert len(rows(client, "hide")) == 2


def test_identical_rows_inside_one_statement_are_not_flagged(session_factory):
    with session_factory() as db:
        user = User(username="u", password_hash="x")
        db.add(user)
        db.flush()
        doc = Document(
            user_id=user.id, sha256="a" * 64, storage_path="p", original_filename="f.pdf",
            size_bytes=1, status="reconciled",
        )  # fmt: skip
        db.add(doc)
        db.flush()
        for seq in (1, 2):
            db.add(
                Transaction(
                    user_id=user.id, document_id=doc.id, seq=seq,
                    transaction_date=date(2022, 9, 5),
                    original_description="SAME", debit=Decimal("5.00"),
                    credit=Decimal("0.00"), running_balance=Decimal("995.00"),
                    source_page=1, row_hash="h" * 64,
                )  # fmt: skip
            )
        db.flush()

        assert refresh_duplicates(db, user.id) == 0


def test_backfill_flags_rows_that_predate_the_columns_and_is_idempotent(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    run_pipeline(client, csrf, session_factory, test_settings, september_and_october())

    with session_factory() as db:  # simulate rows saved before the columns existed
        for tx in db.scalars(select(Transaction)):
            tx.is_duplicate, tx.duplicate_of_id = False, None
        db.commit()
    assert rows(client, "only") == []

    with session_factory() as db:
        assert refresh_all_users(db) == 2
    with session_factory() as db:
        assert refresh_all_users(db) == 2  # running it again changes nothing
    assert len(rows(client, "only")) == 2


def test_duplicates_filter_rejects_unknown_values(logged_in):
    client, _ = logged_in
    assert client.get("/api/transactions?duplicates=maybe").status_code == 422
