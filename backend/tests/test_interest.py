"""Interest worked out from the days a balance was kept. All figures invented."""

from datetime import date
from decimal import Decimal

from app.services import interest

D = Decimal


def account():
    return interest.Account(
        points=[
            (date(2025, 1, 20), D("100000")),
            (date(2025, 2, 11), D("150000")),  # a deposit part-way through February
            (date(2025, 3, 1), D("150405.48")),  # the interest lands in the balance
            (date(2025, 4, 1), D("150916.45")),
        ],
        credits=[(date(2025, 3, 1), D("405.48")), (date(2025, 4, 1), D("510.97"))],
    )


def test_balance_is_the_last_row_on_or_before_the_day():
    points = account().points
    assert interest.balance_on(points, date(2025, 2, 10)) == D("100000")
    assert interest.balance_on(points, date(2025, 2, 11)) == D("150000")
    assert interest.balance_on(points, date(2025, 1, 1)) is None


def test_balance_days_add_up_each_days_balance():
    # February 2025: 10 days at 100,000 then 18 days at 150,000
    total = interest.balance_days(account().points, date(2025, 2, 1), date(2025, 3, 1))
    assert total == D("3700000")
    assert interest.balance_days(account().points, date(2025, 1, 1), date(2025, 2, 1)) is None  # before the data


def test_the_first_credit_pays_for_the_month_before_it():
    first = interest.periods(account())[0]
    assert (first.start, first.days) == (date(2025, 2, 1), 28)
    assert first.balance_days == D("3700000")


def test_the_rate_comes_from_the_days_the_money_was_kept():
    # 3,700,000 balance-days at 4% a year pays 405.48; 405.48 / 3,700,000 x 365 = 4.00%
    rates = interest.monthly_rates([account()], 2025)
    assert [r.month for r in rates] == [3, 4]
    assert rates[0].annual_rate == D("4.00") and rates[0].monthly_rate == D("0.33")
    # the second credit covers the days since the first (March 1 to March 31: 31 days)
    assert rates[1].annual_rate == D("4.00")
    assert rates[1].days == 31


def test_the_naive_month_end_method_would_have_said_something_else():
    # 405.48 on the 150,000 month-end balance for 28 days is 3.52%: the days-kept method is what matches
    naive = 405.48 / 150000 * (365 / 28) * 100
    assert round(naive, 2) == 3.52


def test_a_first_credit_without_a_month_of_data_gets_no_rate():
    short = interest.Account(
        points=[(date(2025, 2, 20), D("100000")), (date(2025, 3, 1), D("100300"))],
        credits=[(date(2025, 3, 1), D("300"))],
    )
    assert interest.periods(short) == []


def test_tax_taken_just_after_the_credit_is_found():
    a = account()
    a.taxes = [(date(2025, 3, 1), D("20.00")), (date(2025, 6, 1), D("99.00"))]
    assert interest.periods(a)[0].tax == D("20.00")


def test_two_accounts_in_a_month_make_one_weighted_rate():
    b = interest.Account(
        points=[(date(2025, 1, 5), D("50000"))],
        credits=[(date(2025, 3, 1), D("123.29"))],  # 50,000 kept for the 28 days of February
    )
    rate = next(r for r in interest.monthly_rates([account(), b], 2025) if r.month == 3)
    assert rate.interest == D("528.77")
    # 528.77 over (3,700,000 + 1,400,000) balance-days: 3.78% a year, not the plain average of two rates
    assert rate.annual_rate == D("3.78")


def test_the_endpoint_works_with_no_data(logged_in):
    client, _ = logged_in
    body = client.get("/api/savings/interest?year=2025").json()
    assert body == {"year": 2025, "accounts": 0, "unrecognised": 0, "months": []}


def test_a_credit_at_the_end_of_the_first_month_pays_for_that_month():
    # the data starts on April 1 and 100,000 earns 6% for 29 days: credited on April 30
    a = interest.Account(
        points=[(date(2025, 3, 31), D("100000")), (date(2025, 4, 30), D("100476.71"))],
        credits=[(date(2025, 4, 30), D("476.71"))],
    )
    rate = interest.monthly_rates([a], 2025)[0]
    assert (rate.annual_rate, rate.assumed) == (D("6.00"), interest.SAME_MONTH)


def test_interest_is_listed_even_when_no_rate_can_be_worked_out():
    # one early credit and too little data before it: the money is still shown, the rate is not
    a = interest.Account(
        points=[(date(2025, 4, 10), D("100000"))],
        credits=[(date(2025, 4, 12), D("50.00"))],
    )
    month = interest.monthly_rates([a], 2025)[0]
    assert month.interest == D("50.00")
    assert month.annual_rate is None and month.unrated == 1


def test_a_month_with_one_rated_and_one_unrated_credit_keeps_both_amounts():
    other = interest.Account(points=[(date(2025, 3, 10), D("1000"))], credits=[(date(2025, 3, 12), D("7.00"))])
    march = next(r for r in interest.monthly_rates([account(), other], 2025) if r.month == 3)
    assert march.interest == D("412.48") and march.unrated == 1
    assert march.annual_rate == D("4.00")  # the rate uses only the credit that has data behind it
