"""IRD (Sri Lanka) figures for a year of assessment. All data synthetic."""

from datetime import date

from app.services import ird

from .test_extraction import run_pipeline
from .test_planning import september


def test_the_year_of_assessment_runs_april_to_march():
    assert ird.bounds(2025) == (date(2025, 4, 1), date(2026, 3, 31))
    assert ird.label(2025) == "2025/26"
    assert ird.label(2099) == "2099/00"
    assert ird.months(2025)[0] == (2025, 4) and ird.months(2025)[-1] == (2026, 3) and len(ird.months(2025)) == 12


def test_today_falls_in_the_right_year_of_assessment():
    assert ird.assessment_year(date(2026, 3, 31)) == 2025
    assert ird.assessment_year(date(2026, 4, 1)) == 2026
    assert ird.assessment_year(date(2026, 11, 9)) == 2026


def test_heads_and_tax_lines_are_sorted_by_what_they_are():
    assert ird.head_of("Salary", "income") == ird.EMPLOYMENT
    assert ird.head_of("Interest income", "income") == ird.INTEREST
    assert ird.head_of("Dividend", "income") == ird.DIVIDENDS
    assert ird.head_of("Deposits", "income") == ird.DEPOSITS
    assert ird.head_of("My side job", "income") == ird.OTHER_INCOME  # a category you made
    assert ird.head_of("Groceries", "expense") is None
    assert ird.head_of("Transfers", "transfer") is None
    assert ird.tax_head("INTEREST WITHHELD TAX") == ird.INTEREST
    assert ird.tax_head("WHT ON DIVIDEND") == ird.DIVIDENDS
    assert ird.tax_head("STAMP DUTY") == "other"


def test_a_year_with_a_salary_shows_it_and_its_month(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())  # a salary of 2,500 in Sep 2022

    report = client.get("/api/reports/ird?year=2022").json()
    assert (report["label"], report["period_start"], report["period_end"]) == ("2022/23", "2022-04-01", "2023-03-31")
    heads = {h["key"]: h for h in report["heads"]}
    assert heads["employment"]["amount"] == "2500.00"
    assert report["total_income"] == "2500.00"
    sep = next(m for m in report["months"] if (m["year"], m["month"]) == (2022, 9))
    assert sep["employment"] == "2500.00"
    assert [l["kind"] for l in report["lines"]] == ["employment"]
    assert report["banks"][0]["employment"] == "2500.00"
    covered = report["coverage"][0]
    assert covered["covered"] == 1 and len(covered["missing"]) == 11  # only September 2022 has a statement


def test_another_year_is_empty(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    report = client.get("/api/reports/ird?year=2023").json()
    assert report["total_income"] == "0.00" and report["lines"] == [] and report["coverage"] == []


def test_the_csv_carries_the_figures_and_a_warning(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    response = client.get("/api/reports/ird.csv?year=2022")
    assert response.status_code == 200
    assert "ird-2022-23.csv" in response.headers["content-disposition"]
    assert "not tax advice" in response.text and "Employment income,2500.00" in response.text


def test_other_wordings_of_withheld_tax_are_recognised():
    for text in ("AIT ON INTEREST", "ADVANCE INCOME TAX 5%", "TAX ON INTEREST", "W/H TAX", "WHT 10%", "INTEREST WITHHELD"):
        assert ird.tax_head(text) == ird.INTEREST, text
    assert ird.tax_head("WITHHOLDING TAX ON DIVIDEND") == ird.DIVIDENDS
    assert ird.tax_head("STAMP DUTY") == "other"
    assert ird.tax_head("WAITING FEE") == "other"  # AIT only counts as a word of its own
    assert ird.tax_head("AIT") == ird.INTEREST and ird.tax_head("TAX AIT 5") == ird.INTEREST


def test_a_tax_line_next_to_an_interest_credit_belongs_to_it():
    credits = [date(2025, 6, 30)]
    assert ird.near(credits, date(2025, 6, 30)) and ird.near(credits, date(2025, 7, 3)) and ird.near(credits, date(2025, 6, 29))
    assert not ird.near(credits, date(2025, 7, 4)) and not ird.near(credits, date(2025, 6, 28))


def test_new_builtin_rules_reach_rows_you_already_have(logged_in, session_factory, test_settings):
    from sqlalchemy import select

    from app.models import Setting, Transaction
    from app.services import categorizer

    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    with session_factory() as db:
        user_id = db.scalar(select(Transaction.user_id).limit(1))
        # a row that no rule matched yet, then the rules grow: an older version is on record
        row = db.scalar(select(Transaction).where(Transaction.original_description == "SYNTHETIC REFUND")) or db.scalar(
            select(Transaction).where(Transaction.original_description == "ATM CASH WITHDRAWAL")
        )
        row.category_id, row.classification_source = None, None
        db.get(Setting, f"categorization_defaults:{user_id}").value = 1
        db.commit()
        categorizer.ensure_defaults(db, user_id)
        db.commit()
        db.refresh(row)
        assert row.category_id is not None  # the cash-withdrawal rule applied on the version bump
