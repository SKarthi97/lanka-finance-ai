"""Bank tracking, filters, pagination, dashboard figures and the statement tracker.
All data is synthetic."""

from decimal import Decimal

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_extraction import run_pipeline

TWO_ROWS = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
]


def september(**kwargs):
    """Reconciles: 1,000 + 2,500 - 500 = 3,000, all in September 2022."""
    return boc_pdf(rows=TWO_ROWS, closing="3,000.00", **kwargs)


def october(closing="2,950.00", **kwargs):
    return boc_pdf(
        statement_date="31/10/2022",
        opening=("30/09", "3,000.00"),
        rows=[("05/10", "POS PURCHASE SYNTHETIC", "50.00", "2,950.00")],
        closing=closing,
        **kwargs,
    )


# --- bank tracking on every transaction ------------------------------------------


def test_each_transaction_says_which_bank_and_account(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september(account=FAKE_ACCOUNT))

    item = client.get("/api/transactions").json()["items"][0]
    assert item["bank_code"] == "boc"
    assert item["bank_name"] == "Bank of Ceylon"
    assert item["account_last4"] == FAKE_ACCOUNT[-4:]
    assert FAKE_ACCOUNT not in str(item)  # never the full number

    assert client.get("/api/transactions?bank_code=boc").json()["total"] == 2
    assert client.get("/api/transactions?bank_code=hnb").json()["total"] == 0


def test_banks_list(logged_in):
    client, _ = logged_in
    assert client.get("/api/banks").json() == [{"code": "boc", "name": "Bank of Ceylon"}]


# --- filters and pagination --------------------------------------------------------


def test_year_and_month_filters(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    assert client.get("/api/transactions?year=2022").json()["total"] == 2
    assert client.get("/api/transactions?year=2022&month=9").json()["total"] == 2
    assert client.get("/api/transactions?year=2022&month=10").json()["total"] == 0
    assert client.get("/api/transactions?year=2023").json()["total"] == 0
    assert client.get("/api/transactions?year=2022&month=13").status_code == 422


def test_december_month_filter_does_not_overflow_the_year(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            statement_date="31/12/2022",
            opening=("30/11", "1,000.00"),
            rows=[("15/12", "DECEMBER ROW", "100.00", "900.00")],
            closing="900.00",
        ),
    )
    assert client.get("/api/transactions?year=2022&month=12").json()["total"] == 1
    assert client.get("/api/dashboard?year=2022&month=12").json()["month"]["transactions"] == 1


def test_pagination_walks_every_row_exactly_once(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    rows, balance = [], 10000
    for day in range(1, 8):
        balance -= 100
        rows.append((f"{day:02d}/09", f"POS PURCHASE {day}", "100.00", f"{balance}.00"))
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(opening=("30/08", "10000.00"), rows=rows, closing=f"{balance}.00"),
    )

    seen = []
    for offset in (0, 3, 6):
        page = client.get(f"/api/transactions?limit=3&offset={offset}").json()
        assert page["total"] == 7
        seen += [t["description"] for t in page["items"]]
    assert sorted(seen) == sorted(r[1] for r in rows)
    assert len(set(seen)) == 7  # no row twice, none missing


# --- dashboard ---------------------------------------------------------------------


def test_dashboard_balance_income_and_expense(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    body = client.get("/api/dashboard?year=2022&month=9").json()
    assert body["has_data"] is True
    assert Decimal(body["total_balance"]) == Decimal("3000.00")
    assert body["as_of"] == "2022-09-30"
    (balance,) = body["balances"]
    assert balance["bank_code"] == "boc"
    assert Decimal(balance["balance"]) == Decimal("3000.00")

    assert Decimal(body["month"]["income"]) == Decimal("2500.00")
    assert Decimal(body["month"]["expense"]) == Decimal("500.00")
    assert Decimal(body["month"]["net"]) == Decimal("2000.00")
    assert body["month"]["transactions"] == 2
    assert Decimal(body["year"]["income"]) == Decimal("2500.00")


def test_dashboard_periods_are_independent(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    other_month = client.get("/api/dashboard?year=2022&month=10").json()
    assert Decimal(other_month["month"]["income"]) == 0
    assert Decimal(other_month["year"]["income"]) == Decimal("2500.00")  # same year

    other_year = client.get("/api/dashboard?year=2023&month=9").json()
    assert other_year["year"]["transactions"] == 0
    assert Decimal(other_year["total_balance"]) == Decimal("3000.00")  # balance is "current"


def test_dashboard_with_no_data(logged_in):
    client, _ = logged_in
    body = client.get("/api/dashboard?year=2026&month=11").json()
    assert body["has_data"] is False
    assert body["balances"] == []
    assert Decimal(body["total_balance"]) == 0
    assert body["as_of"] is None
    assert Decimal(body["month"]["net"]) == 0


def test_dashboard_uses_latest_statement_and_skips_unreconciled(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september(account=FAKE_ACCOUNT))
    run_pipeline(client, csrf, session_factory, test_settings, october(account=FAKE_ACCOUNT))
    run_pipeline(  # November does NOT reconcile (closing 1.00)
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            account=FAKE_ACCOUNT,
            statement_date="30/11/2022",
            opening=("31/10", "2,950.00"),
            rows=[("05/11", "NOV PURCHASE SYNTHETIC", "50.00", "2,900.00")],
            closing="1.00",
        ),
    )

    body = client.get("/api/dashboard?year=2022&month=11").json()
    assert len(body["balances"]) == 1  # one account, however many statements
    assert Decimal(body["total_balance"]) == Decimal("2950.00")  # October, not November
    assert body["as_of"] == "2022-10-31"
    assert body["needs_review"] == 1
    assert Decimal(body["month"]["expense"]) == 0  # the unreconciled November is excluded


# --- tracker ------------------------------------------------------------------------


def test_tracker_marks_months_with_statements(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    sep = run_pipeline(
        client, csrf, session_factory, test_settings, september(account=FAKE_ACCOUNT)
    )
    oct_ = run_pipeline(  # does not reconcile
        client, csrf, session_factory, test_settings, october(closing="1.00", account=FAKE_ACCOUNT)
    )

    body = client.get("/api/tracker?year=2022").json()
    assert body["year"] == 2022
    (row,) = body["rows"]
    assert row["bank_code"] == "boc"
    assert row["account_last4"] == FAKE_ACCOUNT[-4:]
    assert row["cells"] == {
        "9": {"status": "ok", "document_id": sep},
        "10": {"status": "review", "document_id": oct_},
    }

    other = client.get("/api/tracker?year=2021").json()
    assert other["years"] == [2021, 2022]
    assert other["rows"][0]["cells"] == {}  # known account, nothing for 2021


def test_tracker_is_empty_without_statements(logged_in):
    client, _ = logged_in
    body = client.get("/api/tracker?year=2026").json()
    assert body["rows"] == []
    assert body["years"] == [2026]


# --- re-running extraction ------------------------------------------------------------


def test_reprocess_replaces_transactions_without_duplicating(
    logged_in, session_factory, test_settings
):
    from app.models import Transaction
    from app.worker import process_one
    from sqlalchemy import select

    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(closing="999.00"))
    headers = {"X-CSRF-Token": csrf}  # needs_review keeps its file

    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 403  # CSRF
    response = client.post(f"/api/documents/{doc_id}/reprocess", headers=headers)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    # while queued it cannot be queued again
    assert client.post(f"/api/documents/{doc_id}/reprocess", headers=headers).status_code == 409

    assert process_one(session_factory, "w1", test_settings) is True
    with session_factory() as db:
        assert len(db.scalars(select(Transaction)).all()) == 1  # replaced, not doubled
    assert client.get(f"/api/documents/{doc_id}").json()["status"] == "needs_review"


def test_reprocess_needs_the_original_file(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, september())  # reconciled -> file deleted

    response = client.post(f"/api/documents/{doc_id}/reprocess", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "file_not_retained"


def test_accepted_statements_cannot_be_reprocessed(logged_in, session_factory, test_settings):
    test_settings.retain_documents = True
    client, csrf = logged_in
    headers = {"X-CSRF-Token": csrf}
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(closing="999.00"))
    client.post(f"/api/documents/{doc_id}/accept", headers=headers)

    response = client.post(f"/api/documents/{doc_id}/reprocess", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_accepted"


# --- statements that span several years ----------------------------------------------


def multi_year_statement(**kwargs):
    """Dec 2020 to Jun 2022: dates carry no year, so the adapter walks back from the end.
    1,000 less 10 per row, 7 rows -> 930."""
    rows = [
        ("31/12", "ROW 1", "10.00", "990.00"),  # 2020
        ("06/01", "ROW 2", "10.00", "980.00"),  # 2021
        ("15/06", "ROW 3", "10.00", "970.00"),  # 2021
        ("20/12", "ROW 4", "10.00", "960.00"),  # 2021
        ("10/03", "ROW 5", "10.00", "950.00"),  # 2022
        ("30/06", "ROW 6", "10.00", "940.00"),  # 2022
    ]
    return boc_pdf(
        statement_date="30/06/2022",
        opening=("28/12", "1,000.00"),
        rows=rows,
        closing="940.00",
        **kwargs,
    )


def test_year_selectors_include_every_year_with_transactions(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, multi_year_statement())

    dashboard = client.get("/api/dashboard?year=2026&month=11").json()
    assert dashboard["years"] == [2020, 2021, 2022, 2026]  # old years + the requested one

    tracker = client.get("/api/tracker?year=2026").json()
    assert tracker["years"] == [2020, 2021, 2022, 2026]


def test_old_years_can_be_chosen_on_the_dashboard(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, multi_year_statement())

    dec_2021 = client.get("/api/dashboard?year=2021&month=12").json()
    assert dec_2021["month"]["transactions"] == 1  # ROW 4, 20/12/2021
    assert Decimal(dec_2021["month"]["expense"]) == Decimal("10.00")
    assert dec_2021["year"]["transactions"] == 3  # rows 2, 3 and 4

    assert client.get("/api/transactions?year=2020").json()["total"] == 1
    assert client.get("/api/transactions?year=2021").json()["total"] == 3


def test_tracker_ticks_every_month_a_long_statement_covers(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, multi_year_statement())

    def months(year):
        (row,) = client.get(f"/api/tracker?year={year}").json()["rows"]
        assert {c["document_id"] for c in row["cells"].values()} <= {doc_id}
        return sorted(int(m) for m in row["cells"])

    assert months(2021) == list(range(1, 13))  # every month of a year fully inside
    assert months(2022) == [1, 2, 3, 4, 5, 6]  # up to the month the statement ends
    assert months(2020) == []  # the opening month (28 Dec) is only partly covered


# --- which months a statement counts for ----------------------------------------------


def test_covered_months_rule():
    from datetime import date

    from app.routers.overview import _covered_months

    # A monthly statement counts for its end month only, so a missing month stays visible.
    assert _covered_months(date(2022, 10, 31), date(2022, 11, 30)) == {(2022, 11)}
    assert _covered_months(date(2022, 8, 30), date(2022, 9, 30)) == {(2022, 9)}
    # No opening date: just the end month.
    assert _covered_months(None, date(2022, 11, 30)) == {(2022, 11)}
    # A statement ending mid-month still counts for that month.
    assert _covered_months(date(2022, 10, 31), date(2022, 11, 15)) == {(2022, 11)}
    # A long statement fills every month wholly inside it, plus the end month.
    months = _covered_months(date(2021, 12, 31), date(2022, 6, 30))
    assert months == {(2022, m) for m in range(1, 7)}
    # Across a year boundary.
    assert _covered_months(date(2020, 12, 28), date(2022, 6, 30)) == (
        {(2021, m) for m in range(1, 13)} | {(2022, m) for m in range(1, 7)}
    )
