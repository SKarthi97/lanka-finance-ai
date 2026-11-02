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


# --- multi-page layouts: carry-forwards and repeated headers -------------------------

PAGE_HEADER = [
    "BANK OF CEYLON",
    "STATEMENT OF ACCOUNT",
    "SYNTHETIC CUSTOMER NAME",
    "1 SYNTHETIC ROAD",
    "DATE: 30/09/2022",
    "PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE",
]  # fmt: skip


def carry_forward_pages(page_two_b_f: str = "1,100.00") -> list[str]:
    page_one = PAGE_HEADER + [
        "30/08", "BALANCE B/F", "1000.00",
        "05/09", "ATM CASH WITHDRAWAL", "100.00", "900.00",
        "10/09", "DEPOSIT SYNTHETIC", "200.00", "1,100.00",
        "10/09", "BALANCE C/F", "1,100.00",
        "Page 1 of 2",
    ]  # fmt: skip
    page_two = PAGE_HEADER + [
        "10/09", "BALANCE B/F", page_two_b_f,
        "20/09", "POS PURCHASE SYNTHETIC", "100.00", "1,000.00",
        "30/09", "BALANCE C/F", "1,000.00",
        "Page 2 of 2",
    ]  # fmt: skip
    return ["\n".join(page_one), "\n".join(page_two)]


def test_page_carry_forwards_do_not_replace_the_opening_balance():
    statement = adapter.parse(carry_forward_pages())

    assert statement.opening_balance == Decimal("1000.00")  # the FIRST B/F only
    assert statement.period_start == date(2022, 8, 30)
    assert statement.closing_balance == Decimal("1000.00")  # the LAST C/F
    assert [t.page_no for t in statement.transactions] == [1, 1, 2]
    assert statement.issues == []

    from app.services.validation import validate

    assert validate(statement).reconciled is True


def test_repeated_page_header_does_not_leak_into_descriptions():
    statement = adapter.parse(carry_forward_pages())
    for tx in statement.transactions:
        assert "SYNTHETIC CUSTOMER" not in tx.description
        assert "SYNTHETIC ROAD" not in tx.description
    assert statement.transactions[1].description == "DEPOSIT SYNTHETIC"


def test_carry_forward_that_does_not_continue_is_flagged():
    statement = adapter.parse(carry_forward_pages(page_two_b_f="1,150.00"))

    assert statement.opening_balance == Decimal("1000.00")  # unchanged
    assert [i.code for i in statement.issues] == ["carry_forward_mismatch"]

    from app.services.validation import validate

    assert validate(statement).reconciled is False


def test_row_split_across_a_page_break_stays_one_row():
    page_one = PAGE_HEADER + [
        "30/08", "BALANCE B/F", "1000.00",
        "05/09", "POS PURCHASE", "SYNTHETIC SHOP",
    ]  # fmt: skip
    page_two = PAGE_HEADER + [
        "100.00", "900.00",
        "30/09", "BALANCE C/F", "900.00",
    ]  # fmt: skip
    statement = adapter.parse(["\n".join(page_one), "\n".join(page_two)])

    (tx,) = statement.transactions
    assert tx.description == "POS PURCHASE SYNTHETIC SHOP"
    assert (tx.debit, tx.balance, tx.page_no) == (Decimal("100.00"), Decimal("900.00"), 1)
    assert statement.issues == []


# --- opening balance reading ---------------------------------------------------------


def test_opening_balance_row_with_several_amounts_uses_the_balance_column():
    lines = boc_lines()
    lines[lines.index("BALANCE B/F") + 1] = "0.00"  # an extra amount before the balance
    lines.insert(lines.index("BALANCE B/F") + 2, "1000.00")
    statement = adapter.parse(to_pages(lines))

    assert statement.opening_balance == Decimal("1000.00")  # rightmost = balance column
    assert [i.code for i in statement.issues] == ["opening_balance_ambiguous"]

    from app.services.validation import validate

    assert validate(statement).reconciled is True  # reconciliation confirms the reading


def test_wrong_reading_of_an_ambiguous_opening_balance_is_caught():
    lines = boc_lines()
    lines[lines.index("BALANCE B/F") + 1] = "1000.00"
    lines.insert(lines.index("BALANCE B/F") + 2, "777.00")  # last amount is NOT the balance
    statement = adapter.parse(to_pages(lines))

    from app.services.validation import validate

    assert validate(statement).reconciled is False  # the balance checks refuse it


def test_unreadable_first_opening_balance_is_not_replaced_by_a_carry_forward():
    first = PAGE_HEADER + [
        "30/08", "BALANCE B/F",  # no amount at all
        "05/09", "ATM CASH WITHDRAWAL", "100.00", "900.00",
        "10/09", "BALANCE C/F", "900.00",
    ]  # fmt: skip
    second = PAGE_HEADER + [
        "10/09", "BALANCE B/F", "900.00",  # a carry-forward, NOT the opening balance
        "20/09", "POS PURCHASE SYNTHETIC", "100.00", "800.00",
        "30/09", "BALANCE C/F", "800.00",
    ]  # fmt: skip
    statement = adapter.parse(["\n".join(first), "\n".join(second)])

    assert statement.opening_balance is None
    assert "opening_balance_unidentified" in [i.code for i in statement.issues]

    from app.services.validation import validate

    assert validate(statement).reconciled is False


# --- multi-year statements, zero balances and page furniture -----------------------------


def test_years_are_assigned_by_walking_back_from_the_statement_date():
    """A statement spanning several years prints dates without years."""
    statement = parse(
        statement_date="30/06/2022",
        opening=("28/12", "1,000.00"),
        rows=[
            ("31/12", "R1", "10.00", "990.00"),  # 2020: December before a January
            ("06/01", "R2", "10.00", "980.00"),  # 2021
            ("15/06", "R3", "10.00", "970.00"),  # 2021
            ("20/12", "R4", "10.00", "960.00"),  # 2021: December again
            ("10/03", "R5", "10.00", "950.00"),  # 2022
            ("30/06", "R6", "10.00", "940.00"),  # 2022, the statement date itself
        ],
        closing="940.00",
    )

    assert statement.period_start == date(2020, 12, 28)
    assert [t.date for t in statement.transactions] == [
        date(2020, 12, 31),
        date(2021, 1, 6),
        date(2021, 6, 15),
        date(2021, 12, 20),
        date(2022, 3, 10),
        date(2022, 6, 30),
    ]

    from app.services.validation import validate

    assert validate(statement).reconciled is True


def test_a_leap_day_in_a_multi_year_statement_resolves_to_a_leap_year():
    statement = parse(
        statement_date="30/06/2022",
        opening=("20/02", "1,000.00"),
        rows=[
            ("29/02", "LEAP DAY", "10.00", "990.00"),  # only valid in 2020
            ("05/03", "AFTER", "10.00", "980.00"),
            ("10/01", "NEXT YEAR", "10.00", "970.00"),  # 2021
            ("15/12", "LATER", "10.00", "960.00"),  # 2021
            ("20/03", "LAST YEAR", "10.00", "950.00"),  # 2022
        ],
        closing="950.00",
    )
    assert statement.issues == []
    assert statement.transactions[0].date == date(2020, 2, 29)


def test_page_furniture_after_the_amounts_is_not_part_of_the_description():
    lines = boc_lines(rows=[], closing=None)
    lines += [
        "24/09", "ATM SERVICE CHARGE", "5.00", "995.00",
        # trailing footer + next page header + end-of-statement notes, as extracted
        "page no: 8", "SYNTHETIC-IT",
        "All the transactions shown on the statement should be verified.",
        "ACCOUNT NO", ":", "9990001111",
        "BRANCH CODE/NAME", ":", "500 SYNTHETIC BRANCH",
        "CURRENCY", ":", "LKR",
        "END OF STATEMENT", "For clarifications, please contact the Branch Manager.",
        "30/09", "BALANCE C/F", "995.00",
    ]  # fmt: skip
    statement = adapter.parse(to_pages(lines))

    (tx,) = statement.transactions
    assert tx.description == "ATM SERVICE CHARGE"
    assert tx.debit == Decimal("5.00")
    assert statement.closing_balance == Decimal("995.00")


def test_wrapped_description_before_the_amounts_is_still_complete():
    statement = parse(rows=[("05/09", ["LINE ONE", "LINE TWO", "LINE THREE"], "100.00", "900.00")])
    assert statement.transactions[0].description == "LINE ONE LINE TWO LINE THREE"


def test_description_after_the_amounts_is_a_fallback_for_odd_extraction_order():
    statement = parse(rows=[("05/09", "100.00", "900.00", "ODD ORDER ROW")])
    assert statement.transactions[0].description == "ODD ORDER ROW"
    assert statement.transactions[0].debit == Decimal("100.00")


def test_zero_is_printed_without_a_leading_digit():
    """BOC prints nil as '.00'. A nil opening balance must still be read."""
    statement = parse(
        opening=("01/09", ".00"),
        rows=[("02/09", "FIRST DEPOSIT", "500.00", "500.00")],
        closing="500.00",
    )
    assert statement.opening_balance == Decimal("0.00")
    assert statement.issues == []
    assert statement.transactions[0].credit == Decimal("500.00")

    from app.services.validation import validate

    assert validate(statement).reconciled is True


def test_balance_that_returns_to_zero_is_read():
    statement = parse(rows=[("05/09", "EMPTY THE ACCOUNT", "1,000.00", ".00")], closing=".00")
    (tx,) = statement.transactions
    assert tx.debit == Decimal("1000.00")
    assert tx.balance == Decimal("0.00")
    assert statement.closing_balance == Decimal("0.00")
