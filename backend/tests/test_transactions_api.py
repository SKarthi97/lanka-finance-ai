from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog, Document

from .synthetic import boc_pdf
from .test_extraction import run_pipeline

TWO_ROWS = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
]


def good_statement(**kwargs):
    return boc_pdf(rows=TWO_ROWS, closing="3,000.00", **kwargs)


def test_transactions_require_login(client):
    assert client.get("/api/transactions").status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/tracker").status_code == 401
    assert client.get("/api/banks").status_code == 401


def test_list_filter_and_search_transactions(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, good_statement())

    body = client.get("/api/transactions").json()
    assert body["total"] == 2
    # newest first
    assert [t["description"] for t in body["items"]] == [
        "ATM CASH WITHDRAWAL",
        "SALARY CREDIT SYNTHETIC",
    ]
    first = body["items"][0]
    assert Decimal(first["debit"]) == Decimal("500.00")  # money travels as exact strings
    assert first["source_page"] == 1
    assert first["validation_status"] == "ok"

    assert client.get(f"/api/transactions?document_id={doc_id}").json()["total"] == 2
    assert client.get("/api/transactions?document_id=999").json()["total"] == 0
    assert client.get("/api/transactions?q=salary").json()["total"] == 1  # case-insensitive
    assert client.get("/api/transactions?limit=1&offset=1").json()["items"][0][
        "description"
    ] == "SALARY CREDIT SYNTHETIC"
    assert client.get("/api/transactions?limit=0").status_code == 422
    assert client.get("/api/transactions?limit=9999").status_code == 422


def test_document_detail_includes_validation_and_balances(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, good_statement())

    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "reconciled"
    assert detail["adapter"] == "boc"
    assert detail["transaction_count"] == 2
    assert Decimal(detail["opening_balance"]) == Decimal("1000.00")
    assert Decimal(detail["closing_balance"]) == Decimal("3000.00")
    assert detail["validation"]["reconciled"] is True
    assert detail["extraction_confidence"] == 1.0
    assert detail["file_available"] is False  # deleted after reconciliation


def test_accepting_a_reviewed_statement_includes_it(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(closing="999.00")
    )
    assert client.get("/api/dashboard?year=2022&month=9").json()["year"]["transactions"] == 0

    assert client.post(f"/api/documents/{doc_id}/accept").status_code == 403  # CSRF
    accepted = client.post(
        f"/api/documents/{doc_id}/accept", headers={"X-CSRF-Token": csrf}
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    dashboard = client.get("/api/dashboard?year=2022&month=9").json()
    assert dashboard["needs_review"] == 0
    assert dashboard["year"]["transactions"] == 1

    with session_factory() as db:
        assert "document.accept" in [a.action for a in db.scalars(select(AuditLog))]
        assert db.get(Document, doc_id).file_deleted_at is not None  # retention applies

    # only statements needing review can be accepted
    again = client.post(f"/api/documents/{doc_id}/accept", headers={"X-CSRF-Token": csrf})
    assert again.status_code == 409


def test_page_image_for_a_retained_file(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(closing="999.00")
    )  # needs_review, so the file is kept

    response = client.get(f"/api/documents/{doc_id}/pages/1/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert "no-store" in response.headers["cache-control"]

    assert client.get(f"/api/documents/{doc_id}/pages/2/image").status_code == 404


def test_page_image_after_the_file_was_deleted(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, good_statement())

    response = client.get(f"/api/documents/{doc_id}/pages/1/image")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_retained"


def test_deleting_a_document_removes_its_transactions(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, good_statement())
    assert client.get("/api/transactions").json()["total"] == 2

    assert (
        client.delete(f"/api/documents/{doc_id}", headers={"X-CSRF-Token": csrf}).status_code
        == 204
    )
    assert client.get("/api/transactions").json()["total"] == 0


def test_flagged_filter_returns_only_rows_that_failed_checks(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(rows=[("05/09", "ODD ROW", "100.00", "850.00")], closing="850.00"),
    )
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            statement_date="31/10/2022",
            opening=("30/09", "900.00"),
            rows=[("05/10", "CLEAN ROW", "50.00", "850.00")],
            closing="850.00",
        ),
    )

    assert client.get("/api/transactions").json()["total"] == 2
    flagged = client.get("/api/transactions?flagged=true").json()
    assert [t["description"] for t in flagged["items"]] == ["ODD ROW"]
    assert flagged["items"][0]["validation_status"] == "balance_mismatch"
