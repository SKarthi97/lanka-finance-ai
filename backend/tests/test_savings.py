"""Savings insights: what banks pay, a falling rate, idle money and the projection. Invented figures."""

from datetime import date, timedelta
from decimal import Decimal

from app.services import interest, savings

D = Decimal


def monthly_account(rate_by_month, start_balance=D("100000"), first=date(2025, 1, 1)):
    """An account holding 100,000 that is credited interest on the 1st of each following month at the
    given annual rates (a list of percentages, one per month, starting with the credit on `first`+1 month)."""
    points = [(first - timedelta(days=1), start_balance)]  # the balance stays at this level throughout
    credits = []
    day = first
    for pct in rate_by_month:
        nxt = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        amount = (start_balance * D(str(pct)) / 100 * (nxt - day).days / 365).quantize(D("0.01"))
        credits.append((nxt, amount))
        day = nxt
    return interest.Account(points=points, credits=credits)


def info(account, code="boc", name="Bank of Ceylon", last4="1111"):
    return savings.AccountInfo(code, name, last4, account)


def test_a_bank_that_pays_more_comes_first():
    infos = [
        info(monthly_account([4, 4, 4, 4]), "boc", "Bank of Ceylon"),
        info(monthly_account([6, 6, 6, 6]), "hnb", "Hatton National Bank", "2222"),
    ]
    banks = savings.bank_rates(infos, date(2025, 6, 1))
    assert [b.bank_code for b in banks] == ["hnb", "boc"]
    assert banks[0].annual_rate == D("6.00") and banks[1].annual_rate == D("4.00")
    assert banks[0].accounts == 1


def test_a_falling_rate_is_noticed_and_a_steady_one_is_not():
    falling = info(monthly_account([6, 6, 6, 5]))
    drop = savings.rate_drops([falling])
    assert len(drop) == 1 and drop[0].previous_rate == D("6.00") and drop[0].latest_rate == D("5.00")
    assert savings.rate_drops([info(monthly_account([6, 6, 6, 6]))]) == []
    assert savings.rate_drops([info(monthly_account([6, 6, 5.8]))]) == []  # under half a point is not news
    assert savings.rate_drops([info(monthly_account([6, 5]))]) == []  # too little history to judge


def test_a_quiet_account_with_money_in_it_is_idle_and_one_that_pays_is_not():
    today = date(2025, 9, 30)
    quiet = interest.Account(points=[(date(2025, 5, 1), D("200000"))])
    paying = monthly_account([4] * 8)
    found = savings.idle_accounts([info(quiet, last4="3333"), info(paying)], today, D("6.00"))
    assert [f.last4 for f in found] == ["3333"]
    assert found[0].average_balance == D("200000.00")
    assert found[0].could_earn_a_year == D("12000.00")


def test_small_or_stale_accounts_are_not_called_idle():
    today = date(2025, 9, 30)
    small = interest.Account(points=[(date(2025, 5, 1), D("5000"))])
    stale = info(interest.Account(points=[(date(2025, 2, 1), D("200000"))]))
    stale.last_covered = date(2025, 3, 1)  # its statements stopped six months before "today"
    assert savings.idle_accounts([info(small)], today, D("6.00")) == []
    assert savings.idle_accounts([stale], today, D("6.00")) == []


def test_no_known_rate_means_no_estimate():
    quiet = interest.Account(points=[(date(2025, 5, 1), D("200000"))])
    found = savings.idle_accounts([info(quiet)], date(2025, 9, 30), None)
    assert found[0].could_earn_a_year is None


def test_the_projection_continues_the_recent_monthly_change():
    # +10,000 a month from 1 Jan to 1 Aug
    points = [(date(2025, m, 1), D(100000 + 10000 * (m - 1))) for m in range(1, 9)]
    plan = savings.projection([info(interest.Account(points=points))], date(2025, 8, 1), D("250000"))
    assert plan is not None
    assert plan.monthly_change == D("10000.00") and plan.current_balance == D("170000.00")
    assert len(plan.points) == savings.PROJECTION_MONTHS
    assert plan.points[0][1] == D("180000.00") and plan.points[-1][1] == D("290000.00")
    assert plan.months_to_goal == 8 and not plan.goal_reached  # 80,000 more at 10,000 a month


def test_a_goal_already_met_and_a_shrinking_balance():
    points = [(date(2025, m, 1), D(100000 - 5000 * (m - 1))) for m in range(1, 9)]
    plan = savings.projection([info(interest.Account(points=points))], date(2025, 8, 1), D("100000"))
    assert plan.monthly_change < 0 and plan.months_to_goal is None and not plan.goal_reached
    rich = savings.projection([info(interest.Account(points=points))], date(2025, 8, 1), D("10000"))
    assert rich.goal_reached


def test_no_accounts_gives_no_projection():
    assert savings.projection([], date(2025, 8, 1), None) is None


def test_the_endpoints_work_with_no_data(logged_in):
    client, _ = logged_in
    body = client.get("/api/savings/insights").json()
    assert body == {"as_of": None, "banks": [], "best_rate": None, "drops": [], "idle": [], "projection": None}
    assert client.get("/api/savings/interest?year=2025").json()["months"] == []
