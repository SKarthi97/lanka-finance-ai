"""Sorting, CSV export, bulk category changes and AI suggestion review. Synthetic data only."""

import csv
import io

from app.models import Transaction
from app.routers.transactions import _safe

from .test_extraction import run_pipeline
from .test_overview_api import september

HEADERS = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


def descriptions(client, query=""):
    return [t["description"] for t in client.get(f"/api/transactions{query}").json()["items"]]


def category_ids(client):
    return {c["name"]: c["id"] for c in client.get("/api/categories").json()}


# --- sorting ---------------------------------------------------------------------------------


def test_sorting_by_amount_description_and_date(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    # Rows: 02/09 SALARY CREDIT SYNTHETIC (2,500 credit), 05/09 ATM CASH WITHDRAWAL (500 debit)
    assert descriptions(client, "?sort=amount&order=desc")[0] == "SALARY CREDIT SYNTHETIC"
    assert descriptions(client, "?sort=amount&order=asc")[0] == "ATM CASH WITHDRAWAL"
    assert descriptions(client, "?sort=description&order=asc")[0] == "ATM CASH WITHDRAWAL"
    assert descriptions(client, "?sort=date&order=asc")[0] == "SALARY CREDIT SYNTHETIC"
    assert descriptions(client)[0] == "ATM CASH WITHDRAWAL"  # default: newest first


def test_unknown_sort_is_rejected(logged_in):
    client, _ = logged_in
    assert client.get("/api/transactions?sort=password").status_code == 422
    assert client.get("/api/transactions?order=sideways").status_code == 422


# --- CSV export ------------------------------------------------------------------------------


def test_csv_export_matches_the_filters(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    response = client.get("/api/transactions/export.csv?sort=date&order=asc")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM for Excel

    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["date", "bank", "account_last4", "description"]
    assert len(rows) == 3  # header + both transactions, not one page
    assert rows[1][3] == "SALARY CREDIT SYNTHETIC"
    assert rows[1][5] == "2500.00"  # credit, exact decimal

    only_one = client.get("/api/transactions/export.csv?q=SALARY").content.decode("utf-8-sig")
    assert len(list(csv.reader(io.StringIO(only_one)))) == 2

    nothing = client.get("/api/transactions/export.csv?bank_code=hnb").content.decode("utf-8-sig")
    assert len(list(csv.reader(io.StringIO(nothing)))) == 1  # header only


def test_csv_export_requires_login(client):
    assert client.get("/api/transactions/export.csv").status_code == 401


def test_csv_cells_cannot_run_as_formulas():
    assert _safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _safe("+1") == "'+1"
    assert _safe("-1") == "'-1"
    assert _safe("@SUM(A1)") == "'@SUM(A1)"
    assert _safe("ATM CASH") == "ATM CASH"


# --- bulk category ---------------------------------------------------------------------------


def test_bulk_category_sets_and_clears(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    ids = category_ids(client)
    both = [t["id"] for t in client.get("/api/transactions").json()["items"]]

    response = client.post(
        "/api/transactions/bulk-category",
        json={"ids": both, "category_id": ids["Shopping"]},
        headers=HEADERS(csrf),
    )
    assert response.json() == {"changed": 2}
    for t in client.get("/api/transactions").json()["items"]:
        assert t["category_name"] == "Shopping" and t["classification_source"] == "manual"

    cleared = client.post(
        "/api/transactions/bulk-category",
        json={"ids": both[:1], "category_id": None},
        headers=HEADERS(csrf),
    )
    assert cleared.json() == {"changed": 1}


def test_bulk_category_validation(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    ids = category_ids(client)
    some = [t["id"] for t in client.get("/api/transactions").json()["items"]]

    unknown = client.post(
        "/api/transactions/bulk-category",
        json={"ids": some, "category_id": 999999},
        headers=HEADERS(csrf),
    )
    assert unknown.status_code == 404

    empty = client.post(
        "/api/transactions/bulk-category",
        json={"ids": [], "category_id": ids["Shopping"]},
        headers=HEADERS(csrf),
    )
    assert empty.status_code == 422

    # Ids that are not yours (or do not exist) are ignored: no error and no leak.
    ghost = client.post(
        "/api/transactions/bulk-category",
        json={"ids": [987654], "category_id": ids["Shopping"]},
        headers=HEADERS(csrf),
    )
    assert ghost.json() == {"changed": 0}


def test_bulk_category_needs_csrf(logged_in):
    client, _ = logged_in
    response = client.post(
        "/api/transactions/bulk-category", json={"ids": [1], "category_id": None}
    )
    assert response.status_code in (401, 403)


# --- AI suggestions ----------------------------------------------------------------------------


def mark_ai(session_factory, category_id):
    """Pretend the model categorised every transaction (as the worker would)."""
    with session_factory() as db:
        for t in db.query(Transaction).all():
            t.category_id = category_id
            t.classification_source = "llm"
            t.classification_confidence = 0.9
        db.commit()


def test_suggestions_list_accept_and_reject(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    ids = category_ids(client)
    mark_ai(session_factory, ids["Shopping"])

    body = client.get("/api/categorization/suggestions").json()
    assert body["total"] == 2
    assert {g["category_name"] for g in body["groups"]} == {"Shopping"}
    assert all(g["confidence"] == 0.9 for g in body["groups"])

    first, second = body["groups"]
    rejected = client.post(
        "/api/categorization/suggestions/reject",
        json={"stem": first["stem"], "category_id": first["category_id"]},
        headers=HEADERS(csrf),
    )
    assert rejected.json()["changed"] >= 1
    after = client.get("/api/transactions").json()["items"]
    # The rejected group is back in the review queue (no category, no AI label).
    assert any(t["category_id"] is None and t["classification_source"] is None for t in after)

    accepted = client.post(
        "/api/categorization/suggestions/accept",
        json={"stem": second["stem"], "category_id": second["category_id"]},
        headers=HEADERS(csrf),
    )
    assert accepted.status_code == 200 and accepted.json()["changed"] >= 1
    # Accepting teaches a rule, so the suggestion is no longer an AI suggestion.
    remaining = client.get("/api/categorization/suggestions").json()
    assert all(g["stem"] != second["stem"] for g in remaining["groups"])
    assert any(r["origin"] == "correction" for r in client.get("/api/rules").json())


def test_suggestions_reject_unknown_category(logged_in):
    client, csrf = logged_in
    response = client.post(
        "/api/categorization/suggestions/reject",
        json={"stem": "SOMETHING", "category_id": 424242},
        headers=HEADERS(csrf),
    )
    assert response.status_code == 404
