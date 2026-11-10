"""Budgets, recurring detection, saved views and the monthly report. All data synthetic."""

from datetime import date
from decimal import Decimal

from app.services import recurring

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_extraction import run_pipeline

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


def category_ids(client):
    return {c["name"]: c["id"] for c in client.get("/api/categories").json()}


def september(extra_credit=False):
    rows = [
        ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
        ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
    ]
    closing = "3,000.00"
    if extra_credit:
        rows.append(("08/09", "SYNTHETIC REFUND", "100.00", "3,100.00"))
        closing = "3,100.00"
    return boc_pdf(rows=rows, closing=closing, account=FAKE_ACCOUNT)


def file_under(client, csrf, description, category_id):
    items = client.get("/api/transactions?limit=500").json()["items"]
    row = next(t for t in items if t["description"] == description)
    client.put(
        f"/api/transactions/{row['id']}/category",
        json={"category_id": category_id},
        headers=H(csrf),
    )


# --- 3.1 budgets ---------------------------------------------------------------------------


def set_budget(client, csrf, category_id, amount):
    return client.put(
        f"/api/budgets/{category_id}", json={"amount": amount}, headers=H(csrf)
    )


def budgets(client, year=2022, month=9):
    return client.get(f"/api/budgets?year={year}&month={month}").json()


def test_a_budget_tracks_what_was_spent(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    fuel = category_ids(client)["Fuel"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", fuel)

    assert set_budget(client, csrf, fuel, "1000.00").status_code == 200
    line = budgets(client)["items"][0]
    assert (line["spent"], line["limit"], line["remaining"]) == ("500.00", "1000.00", "500.00")
    assert (line["percent"], line["state"]) == (50, "under")


def test_near_and_over(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    fuel = category_ids(client)["Fuel"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", fuel)

    set_budget(client, csrf, fuel, "600.00")  # 83%
    assert budgets(client)["items"][0]["state"] == "near"

    set_budget(client, csrf, fuel, "400.00")  # 125%
    data = budgets(client)
    assert data["items"][0]["state"] == "over"
    assert data["items"][0]["remaining"] == "-100.00"
    assert data["over"] == 1


def test_setting_a_budget_again_changes_it_rather_than_adding_one(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    fuel = category_ids(client)["Fuel"]
    set_budget(client, csrf, fuel, "100.00")
    set_budget(client, csrf, fuel, "250.00")
    items = budgets(client)["items"]
    assert len(items) == 1 and items[0]["limit"] == "250.00"


def test_a_refund_reduces_what_counts_as_spent(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september(extra_credit=True))
    fuel = category_ids(client)["Fuel"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", fuel)
    file_under(client, csrf, "SYNTHETIC REFUND", fuel)

    set_budget(client, csrf, fuel, "1000.00")
    assert budgets(client)["items"][0]["spent"] == "400.00"


def test_other_months_and_transfers_do_not_count(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    fuel = category_ids(client)["Fuel"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", fuel)
    set_budget(client, csrf, fuel, "1000.00")

    assert budgets(client, month=10)["items"][0]["spent"] == "0.00"


def test_budgets_are_for_expense_categories_only(logged_in):
    client, csrf = logged_in
    ids = category_ids(client)
    assert set_budget(client, csrf, ids["Salary"], "100.00").status_code == 422
    assert set_budget(client, csrf, ids["Transfers"], "100.00").status_code == 422
    assert set_budget(client, csrf, 99999, "100.00").status_code == 404


def test_a_budget_must_be_a_positive_amount(logged_in):
    client, csrf = logged_in
    fuel = category_ids(client)["Fuel"]
    assert set_budget(client, csrf, fuel, "0").status_code == 422
    assert set_budget(client, csrf, fuel, "-5").status_code == 422


def test_deleting_a_budget(logged_in):
    client, csrf = logged_in
    fuel = category_ids(client)["Fuel"]
    set_budget(client, csrf, fuel, "100.00")
    assert client.delete(f"/api/budgets/{fuel}", headers=H(csrf)).status_code == 204
    assert budgets(client)["items"] == []
    assert client.delete(f"/api/budgets/{fuel}", headers=H(csrf)).status_code == 404


# --- 3.2 recurring -----------------------------------------------------------------------------


def four_months():
    """Jan-Apr 2022: a 1,500 subscription on the 5th, a 50,000 salary on the 25th, one ATM."""
    rows, balance = [], Decimal("100000.00")

    def add(day, text, amount, credit=False):
        nonlocal balance
        balance += Decimal(amount) if credit else -Decimal(amount)
        rows.append((day, text, f"{Decimal(amount):,.2f}", f"{balance:,.2f}"))

    for month in ("01", "02", "03", "04"):
        add(f"05/{month}", "NETFLIX SYNTHETIC SUBSCRIPTION", "1500.00")
        if month == "04":
            add("14/04", "ATM CASH WITHDRAWAL", "7000.00")
        add(f"25/{month}", "SALARY CREDIT SYNTHETIC", "50000.00", credit=True)
    return boc_pdf(
        statement_date="30/04/2022",
        opening=("31/12", "100,000.00"),
        rows=rows,
        closing=f"{balance:,.2f}",
        account=FAKE_ACCOUNT,
    )


def test_a_monthly_subscription_and_salary_are_found(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, four_months())

    data = client.get("/api/recurring").json()
    found = {r["stem"]: r for r in data["items"]}
    assert set(found) == {"NETFLIX SYNTHETIC SUBSCRIPTION", "SALARY CREDIT SYNTHETIC"}

    netflix = found["NETFLIX SYNTHETIC SUBSCRIPTION"]
    assert (netflix["cadence"], netflix["count"], netflix["direction"]) == ("monthly", 4, "expense")
    assert netflix["typical_amount"] == "1500.00"
    assert netflix["last_date"] == "2022-04-05"

    salary = found["SALARY CREDIT SYNTHETIC"]
    assert (salary["cadence"], salary["direction"]) == ("monthly", "income")
    assert salary["typical_amount"] == "50000.00"
    assert "ATM CASH WITHDRAWAL" not in found  # one-off


def test_states_follow_the_calendar(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, four_months())

    def states(today):
        with session_factory() as db:
            return {r.stem: r.state for r in recurring.find(db, 1, today=today)}

    assert states(date(2022, 4, 20))["NETFLIX SYNTHETIC SUBSCRIPTION"] == "upcoming"
    assert states(date(2022, 5, 3))["NETFLIX SYNTHETIC SUBSCRIPTION"] == "due"
    assert states(date(2022, 5, 25))["NETFLIX SYNTHETIC SUBSCRIPTION"] == "overdue"
    assert states(date(2023, 3, 1))["NETFLIX SYNTHETIC SUBSCRIPTION"] == "ended"


def test_monthly_totals_leave_out_ended_ones(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, four_months())
    # today's real date is long after 2022, so both have ended
    data = client.get("/api/recurring").json()
    assert all(r["state"] == "ended" for r in data["items"])
    assert data["monthly_expense"] == "0.00" and data["monthly_income"] == "0.00"


def test_cadence_needs_regular_gaps():
    assert recurring._cadence([30, 31, 28], 4) == ("monthly", 30)
    assert recurring._cadence([7, 7, 8, 6], 5) == ("weekly", 7)
    assert recurring._cadence([3, 40, 11, 90], 5) is None
    assert recurring._cadence([30, 30], 2) is None  # monthly needs three occurrences


def test_amounts_that_swing_widely_are_not_recurring(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    rows, balance = [], Decimal("100000.00")
    for month, amount in (("01", "1000.00"), ("02", "4000.00"), ("03", "900.00"), ("04", "7000.00")):
        balance -= Decimal(amount)
        rows.append((f"05/{month}", "ELECTRICITY BOARD SYNTHETIC", f"{Decimal(amount):,.2f}", f"{balance:,.2f}"))
    pdf = boc_pdf(
        statement_date="30/04/2022",
        opening=("31/12", "100,000.00"),
        rows=rows,
        closing=f"{balance:,.2f}",
        account=FAKE_ACCOUNT,
    )
    run_pipeline(client, csrf, session_factory, test_settings, pdf)
    assert client.get("/api/recurring").json()["items"] == []


# --- 3.3 saved views ---------------------------------------------------------------------------


def test_save_list_and_delete_a_view(logged_in):
    client, csrf = logged_in
    saved = client.post(
        "/api/views",
        json={"name": "Fuel in 2026", "filters": {"year": 2026, "category_id": 4, "bank_code": "boc"}},
        headers=H(csrf),
    )
    assert saved.status_code == 201
    view = saved.json()
    assert view["filters"]["year"] == 2026 and view["filters"]["bank_code"] == "boc"
    assert view["filters"]["duplicates"] == "hide"  # unspecified filters take their defaults

    assert [v["name"] for v in client.get("/api/views").json()] == ["Fuel in 2026"]
    assert client.delete(f"/api/views/{view['id']}", headers=H(csrf)).status_code == 204
    assert client.get("/api/views").json() == []
    assert client.delete(f"/api/views/{view['id']}", headers=H(csrf)).status_code == 404


def test_saving_under_the_same_name_replaces_the_view(logged_in):
    client, csrf = logged_in
    for year in (2025, 2026):
        client.post(
            "/api/views", json={"name": "Mine", "filters": {"year": year}}, headers=H(csrf)
        )
    views = client.get("/api/views").json()
    assert len(views) == 1 and views[0]["filters"]["year"] == 2026


def test_a_view_holds_filters_and_nothing_else(logged_in):
    client, csrf = logged_in
    response = client.post(
        "/api/views",
        json={"name": "Sneaky", "filters": {"year": 2026, "sql": "DROP TABLE users"}},
        headers=H(csrf),
    )
    assert response.status_code == 422
    bad_month = client.post(
        "/api/views", json={"name": "Bad", "filters": {"month": 13}}, headers=H(csrf)
    )
    assert bad_month.status_code == 422
    blank = client.post("/api/views", json={"name": "  ", "filters": {}}, headers=H(csrf))
    assert blank.status_code == 422


# --- 3.4 monthly report --------------------------------------------------------------------------


def test_the_monthly_csv_summarises_the_month(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    fuel = category_ids(client)["Fuel"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", fuel)
    set_budget(client, csrf, fuel, "400.00")

    response = client.get("/api/reports/monthly.csv?year=2022&month=9")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "summary-2022-09.csv" in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")

    assert "Monthly summary: September 2022" in text
    assert "Income,2500.00" in text and "Expense,500.00" in text and "Net,2000.00" in text
    assert "By category,Income,Expense,Transactions" in text
    assert "By bank,Income,Expense,Net,Transactions" in text
    assert "Bank of Ceylon" in text
    assert "Fuel,400.00,500.00,-100.00,125,over" in text  # the budget line
    assert "ATM CASH WITHDRAWAL,2022-09-05,500.00,Fuel" in text


def test_an_empty_month_still_produces_a_report(logged_in):
    client, _ = logged_in
    text = client.get("/api/reports/monthly.csv?year=2022&month=1").content.decode("utf-8-sig")
    assert "Monthly summary: January 2022" in text
    assert "Income,0.00" in text


def test_the_report_needs_a_session(client):
    assert client.get("/api/reports/monthly.csv").status_code == 401


def test_a_correction_matches_a_description_with_a_number_between_the_words():
    from app.services.categorizer import Rule, pick_rule

    rule = Rule(1, "CRDLESDEP AECT", "contains", 7, "correction", 100)
    assert pick_rule([rule], "CRDLESDEP 0000769618638 AECT") is rule
    assert pick_rule([rule], "SOMETHING ELSE") is None


def test_dividend_is_an_income_category_with_rules():
    from app.services.categorizer import CATEGORIES, RULES

    assert ("Dividend", "income") in CATEGORIES
    assert any(cat == "Dividend" for _p, _t, cat, _pr in RULES)


# --- sub-categories roll up into their parent ----------------------------------------------


def test_a_parent_budget_and_filter_include_its_sub_categories(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    ids = category_ids(client)
    parent = ids["Food and dining"]
    child = client.post(
        "/api/categories", json={"name": "Groceries", "kind": "expense", "parent_id": parent}, headers=H(csrf)
    ).json()["id"]
    file_under(client, csrf, "ATM CASH WITHDRAWAL", child)

    assert set_budget(client, csrf, parent, "1000.00").status_code == 200
    line = next(b for b in budgets(client)["items"] if b["category_id"] == parent)
    assert line["spent"] == "500.00"  # the sub-category's spending counts against the parent

    listed = client.get(f"/api/transactions?category_id={parent}").json()["items"]
    assert [t["description"] for t in listed] == ["ATM CASH WITHDRAWAL"]

    dash = client.get("/api/dashboard?year=2022&month=9").json()
    row = next(c for c in dash["month_by_category"] if c["category_id"] == child)
    assert (row["parent_id"], row["parent_name"]) == (parent, "Food and dining")


# --- numbers worked out by code ------------------------------------------------------------


def ask(client, csrf, query):
    return client.post("/api/search/interpret", json={"query": query}, headers=H(csrf)).json()


def test_a_question_for_a_total_gets_a_computed_answer(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())

    spent = ask(client, csrf, "how much did I spend in september 2022")
    assert spent["filters"]["direction"] == "out" and spent["filters"]["q"] is None
    assert spent["answer"]["kind"] == "sum"
    assert [(p["label"], p["value"], p["count"]) for p in spent["answer"]["parts"]] == [("Money out", "500.00", 1)]

    both = ask(client, csrf, "total in september 2022")["answer"]["parts"]
    assert [(p["label"], p["value"]) for p in both] == [("Money out", "500.00"), ("Money in", "2500.00")]

    count = ask(client, csrf, "how many transactions in september 2022")["answer"]
    assert [p["value"] for p in count["parts"]] == ["1", "1"]

    biggest = ask(client, csrf, "largest money in september 2022")["answer"]["parts"][0]
    assert biggest["value"] == "2500.00" and "SALARY" in biggest["detail"]

    average = ask(client, csrf, "average spent in september 2022")["answer"]["parts"][0]
    assert average["value"] == "500.00"


def test_a_question_without_a_number_asked_has_no_answer(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    assert ask(client, csrf, "salary in september 2022")["answer"] is None
    nothing = ask(client, csrf, "how much did I spend in january 2020")["answer"]["parts"][0]
    assert (nothing["value"], nothing["count"]) == (None, 0)
