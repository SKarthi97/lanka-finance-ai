from datetime import date
from decimal import Decimal

import pytest

from app.adapters.base import ParseError
from app.adapters.boc import BocAdapter

from .synthetic import FAKE_ACCOUNT, boc_lines, boc_two_pages, to_pages

adapter = BocAdapter()


def parse(**kwargs):
    return adapter.parse(to_pages(boc_lines(**kwargs)))


def test_parses_a_simple_statement_with_exact_decimals():
    statement = parse()

    assert statement.opening_balance == Decimal("1000.00")
    assert statement.closing_balance == Decimal("900.00")
    assert statement.period_start == date(2022, 8, 30)
    assert statement.statement_date == date(2022, 9, 30)
    assert statement.issues == []

    (tx,) = statement.transactions
    assert tx.date == date(2022, 9, 5)
    assert tx.description == "ATM CASH WITHDRAWAL"
    assert tx.debit == Decimal("100.00")
    assert tx.credit == Decimal("0.00")
    assert tx.balance == Decimal("900.00")
    assert isinstance(tx.debit, Decimal)
    assert (tx.seq, tx.page_no) == (1, 1)


def test_debit_and_credit_follow_balance_movement():
    statement = parse(
        rows=[
            ("02/09", "SALARY CREDIT", "2,500.50", "3,500.50"),
            ("03/09", "POS PURCHASE", "500.25", "3,000.25"),
        ],
        closing="3,000.25",
    )
    credit, debit = statement.transactions
    assert (credit.credit, credit.debit) == (Decimal("2500.50"), Decimal("0.00"))
    assert (debit.debit, debit.credit) == (Decimal("500.25"), Decimal("0.00"))


def test_wrapped_description_lines_are_joined():
    statement = parse(rows=[("05/09", ["POS PURCHASE", "SYNTHETIC SHOP", "COLOMBO"], "100.00", "900.00")])
    assert statement.transactions[0].description == "POS PURCHASE SYNTHETIC SHOP COLOMBO"


def test_rows_keep_their_page_and_page_furniture_is_ignored():
    first = boc_lines(closing=None, rows=[("05/09", "ATM CASH WITHDRAWAL", "100.00", "900.00")])
    second = [
        "10/09", "DEPOSIT SYNTHETIC", "50.00", "950.00",
        "30/09", "BALANCE C/F", "950.00",
    ]  # fmt: skip
    statement = adapter.parse(boc_two_pages(first, second))

    assert [t.page_no for t in statement.transactions] == [1, 2]
    assert statement.closing_balance == Decimal("950.00")
    assert statement.issues == []
    # repeated column headers / "Page n of m" never leak into descriptions
    assert statement.transactions[0].description == "ATM CASH WITHDRAWAL"
    assert statement.transactions[1].description == "DEPOSIT SYNTHETIC"


def test_year_is_inferred_across_a_year_boundary():
    statement = parse(
        statement_date="15/01/2023",
        opening=("30/12", "1000.00"),
        rows=[
            ("31/12", "SERVICE CHARGE", "10.00", "990.00"),
            ("02/01", "SALARY CREDIT", "500.00", "1,490.00"),
        ],
        closing="1,490.00",
    )
    assert statement.period_start == date(2022, 12, 30)
    assert [t.date for t in statement.transactions] == [date(2022, 12, 31), date(2023, 1, 2)]


def test_summary_lines_are_not_transactions():
    lines = boc_lines()
    lines[-3:-3] = ["TOTAL DEPOSITS", "0.00", "TOTAL WITHDRAWALS", "100.00"]
    statement = adapter.parse(to_pages(lines))
    assert len(statement.transactions) == 1


def test_row_with_missing_amount_column_is_reported_not_guessed():
    statement = parse(rows=[("05/09", "ATM CASH WITHDRAWAL", "100.00", "900.00"), ("06/09", "BROKEN ROW", "50.00")])
    assert len(statement.transactions) == 1
    assert [i.code for i in statement.issues] == ["unexpected_amount_columns"]


def test_balance_mismatch_is_flagged_on_the_row():
    statement = parse(rows=[("05/09", "ODD ROW", "100.00", "850.00")], closing="850.00")
    (issue,) = statement.issues
    assert (issue.code, issue.seq) == ("balance_mismatch", 1)


def test_rejects_other_layouts_with_codes_only():
    with pytest.raises(ParseError) as no_date:
        adapter.parse(["Some other bank\nNo date here"])
    assert no_date.value.code == "statement_date_not_found"

    with pytest.raises(ParseError) as wrong_format:
        adapter.parse(["DATE: 30/09/2022\nJust some text"])
    assert wrong_format.value.code == "format_mismatch"


def test_identify_scores():
    assert adapter.identify(to_pages(boc_lines())) == 1.0
    assert adapter.identify(to_pages(boc_lines(bank_name=False))) == 0.7
    assert adapter.identify(["Some other statement"]) == 0.0


# --- account number extraction (synthetic number only) ---------------------


def test_account_number_inline_and_label_styles():
    assert parse(account=FAKE_ACCOUNT).account_number == FAKE_ACCOUNT
    assert parse(account=FAKE_ACCOUNT, account_style="label").account_number == FAKE_ACCOUNT
    assert parse().account_number is None


def test_account_number_in_a_description_is_never_picked_up():
    statement = parse(rows=[("05/09", f"TRANSFER TO A/C {FAKE_ACCOUNT}", "100.00", "900.00")])
    assert statement.account_number is None
