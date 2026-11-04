"""The notification bell: what needs attention, derived from the data. All data synthetic."""

from datetime import date, timedelta

from app.services import notifications

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_extraction import run_pipeline


def fetch(client):
    return client.get("/api/notifications").json()


def recent_statement(days_ago: int = 3):
    """A reconciled statement ending `days_ago` days before today."""
    end = date.today() - timedelta(days=days_ago)
    start = end - timedelta(days=5)
    return boc_pdf(
        statement_date=end.strftime("%d/%m/%Y"),
        opening=(start.strftime("%d/%m"), "1000.00"),
        rows=[(end.strftime("%d/%m"), "POS PURCHASE SYNTHETIC", "100.00", "900.00")],
        closing="900.00",
        account=FAKE_ACCOUNT,
    )


def test_nothing_to_report_when_there_is_no_data(logged_in):
    client, _ = logged_in
    assert fetch(client) == {"count": 0, "items": []}


def test_a_current_statement_raises_nothing(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, recent_statement())
    assert fetch(client)["count"] == 0


def test_an_old_statement_reminds_you_to_upload_a_newer_one(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, recent_statement(days_ago=60))

    data = fetch(client)
    assert data["count"] == 1
    notice = data["items"][0]
    assert notice["kind"] == "stale"
    assert "Bank of Ceylon" in notice["text"] and FAKE_ACCOUNT[-4:] in notice["text"]
    assert FAKE_ACCOUNT not in notice["text"]  # never the full number
    assert notice["href"] == "/upload"


def test_the_reminder_goes_away_once_a_newer_statement_is_uploaded(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, recent_statement(days_ago=60))
    assert fetch(client)["count"] == 1

    run_pipeline(client, csrf, session_factory, test_settings, recent_statement(days_ago=2))
    assert all(n["kind"] != "stale" for n in fetch(client)["items"])


def test_a_statement_that_did_not_reconcile_is_reported(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    bad = boc_pdf(
        rows=[("05/09", "ATM CASH WITHDRAWAL", "500.00", "500.00")],
        closing="1.00",
        account=FAKE_ACCOUNT,
    )
    run_pipeline(client, csrf, session_factory, test_settings, bad)

    kinds = [n["kind"] for n in fetch(client)["items"]]
    assert "review" in kinds


def test_notices_never_carry_descriptions_or_amounts(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, recent_statement(days_ago=60))
    text = " ".join(n["text"] for n in fetch(client)["items"])
    assert "POS PURCHASE" not in text and "900" not in text and "1000" not in text


def test_the_month_list_is_short():
    months = [(2026, m) for m in range(1, 8)]
    assert notifications._month_list(months) == "Jan 2026, Feb 2026, Mar 2026, Apr 2026 and 3 more"
    assert notifications._month_list([(2026, 3)]) == "Mar 2026"
