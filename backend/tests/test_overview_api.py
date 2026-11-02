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
