"""The bell tells you when the interest rate you are getting falls. Invented statement."""

from decimal import Decimal

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_extraction import run_pipeline


def statement(rates):
    """100,000 earning interest credited on the 1st of each month at the given annual rates."""
    balance = Decimal("100000.00")
    rows = []
    days = [(1, 2, 31), (1, 3, 28), (1, 4, 31), (1, 5, 30)]
    for (day, month, length), pct in zip(days, rates, strict=False):
        amount = (balance * Decimal(str(pct)) / 100 * length / 365).quantize(Decimal("0.01"))
        balance += amount
        rows.append((f"{day:02d}/{month:02d}", "INTEREST CREDIT SYNTHETIC", f"{amount:,.2f}", f"{balance:,.2f}"))
    return boc_pdf(
        statement_date="01/05/2025",
        opening=("31/12", "100000.00"),
        rows=rows,
        closing=f"{balance:,.2f}",
        account=FAKE_ACCOUNT,
    )


def rate_notices(client):
    return [n for n in client.get("/api/notifications").json()["items"] if n["kind"] == "rate"]


def test_a_falling_rate_reaches_the_bell(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, statement([6, 6, 6, 4]))
    notices = rate_notices(client)
    assert len(notices) == 1 and notices[0]["href"] == "/savings"
    assert "fell from about" in notices[0]["text"] and "% a year" in notices[0]["text"]
    assert "SYNTHETIC" not in notices[0]["text"]  # no description ever reaches a notice


def test_a_steady_rate_stays_quiet(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, statement([6, 6, 6, 6]))
    assert rate_notices(client) == []
    body = client.get("/api/savings/insights").json()
    assert body["banks"][0]["annual_rate"].startswith("6.0") or body["banks"][0]["annual_rate"].startswith("5.9")
