"""Commercial Bank adapter, on synthetic statements only (no real statement, name or number)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.adapters.base import ParseError
from app.adapters.commercial import CommercialAdapter
from app.adapters.registry import select_adapter
from app.models import Bank, Document, Transaction
from app.services.validation import validate

from .synthetic import (
    FAKE_ACCOUNT,
    boc_lines,
    commercial_lines,
    commercial_quarterly_lines,
    hnb_lines,
    pdf_from_pages,
    to_pages,
)
from .test_extraction import run_pipeline

adapter = CommercialAdapter()


def parse(**kwargs):
    return adapter.parse(to_pages(commercial_lines(**kwargs)))


def test_a_simple_statement_reconciles():
    parsed = parse(account=FAKE_ACCOUNT)

    assert parsed.opening_balance == Decimal("1000.00")
    assert parsed.closing_balance == Decimal("900.00")
    assert parsed.statement_date == date(2026, 10, 31)
    assert parsed.period_start == date(2026, 10, 1)
    assert parsed.account_number == FAKE_ACCOUNT

    (row,) = parsed.transactions
    assert row.date == date(2026, 10, 15)
    assert row.description == "SYNTHETIC SHOP PURCHASE"
    assert row.debit == Decimal("100.00") and row.credit == Decimal("0.00")
    assert row.balance == Decimal("900.00")
    assert validate(parsed).reconciled is True


def test_debit_and_credit_are_told_apart_by_the_balance_movement():
    parsed = parse(
        rows=[
            ("05/10/26", "SYNTHETIC INTEREST", "10.00", "1,010.00"),
            ("06/10/26", "SYNTHETIC TAX", "2.00", "1,008.00"),
        ],
        closing=("31/10/26", "1,008.00"),
    )

    interest, tax = parsed.transactions
    assert (interest.credit, interest.debit) == (Decimal("10.00"), Decimal("0.00"))
    assert (tax.debit, tax.credit) == (Decimal("2.00"), Decimal("0.00"))
    assert validate(parsed).reconciled is True


def test_an_overdrawn_balance_is_negative():
    parsed = parse(
        opening=("01/10/26", "100.00 CR"),
        rows=[("05/10/26", "SYNTHETIC SHOP", "250.00", "150.00 DR")],
        closing=("31/10/26", "150.00 DR"),
    )

    (row,) = parsed.transactions
    assert row.balance == Decimal("-150.00") and row.debit == Decimal("250.00")
    assert parsed.closing_balance == Decimal("-150.00")
    assert validate(parsed).reconciled is True


def test_statement_totals_are_read_as_declared_figures():
    parsed = parse(totals=((0, "0.00"), (1, "100.00")))

    assert parsed.declared_withdrawals.count == 1
    assert parsed.declared_withdrawals.total == Decimal("100.00")
    assert parsed.declared_deposits.count == 0
    assert parsed.declared_deposits.total == Decimal("0.00")
    declared = validate(parsed).declared
    assert declared["withdrawals"]["count_match"] is True
    assert declared["withdrawals"]["total_match"] is True


def test_a_balance_that_does_not_add_up_is_flagged():
    parsed = parse(
        rows=[("15/10/26", "SYNTHETIC SHOP", "100.00", "850.00")],
        closing=("31/10/26", "850.00"),
    )

    assert "balance_mismatch" in {issue.code for issue in parsed.issues}
    assert validate(parsed).reconciled is False


def test_a_statement_with_no_dates_cannot_be_parsed():
    with pytest.raises(ParseError) as error:
        adapter.parse(["COMMERCIAL BANK\nSTATEMENT"])
    assert error.value.code == "statement_date_not_found"


def test_missing_opening_and_closing_balances_are_reported():
    parsed = parse(opening=None, closing=None)
    codes = {issue.code for issue in parsed.issues}
    assert {"opening_balance_unidentified", "closing_balance_unidentified"} <= codes


def test_a_row_with_no_amount_is_flagged_not_guessed():
    parsed = parse(rows=[("15/10/26", "SYNTHETIC ODDITY", "", "900.00")])
    # an empty amount line is dropped by the line reader, leaving only a balance
    assert "unexpected_amount_columns" in {issue.code for issue in parsed.issues}
    assert parsed.transactions == []


def test_a_later_page_header_is_not_read_as_a_row():
    first = commercial_lines(closing=None, footer=False)
    second = [
        "31/10/26",
        "LKR",
        FAKE_ACCOUNT,
        "MR SYNTHETIC PERSON",
        "PAGE 2 OF 2",
        "16/10/26",
        "SYNTHETIC SHOP",
        "50.00",
        "850.00 CR",
        "31/10/26",
        "CLOSING BALANCE",
        "850.00 CR",
    ]
    parsed = adapter.parse(["\n".join(first), "\n".join(second)])

    assert [t.description for t in parsed.transactions] == ["SYNTHETIC SHOP PURCHASE", "SYNTHETIC SHOP"]
    assert [t.page_no for t in parsed.transactions] == [1, 2]
    assert parsed.closing_balance == Decimal("850.00")
    assert validate(parsed).reconciled is True


def test_a_wrapped_description_is_joined_and_the_footer_is_not():
    parsed = adapter.parse(
        [
            "\n".join(
                [
                    "31/10/26",
                    "LKR",
                    "01/10/26",
                    "OPENING BALANCE",
                    "1,000.00 CR",
                    "15/10/26",
                    "SYNTHETIC LONG",
                    "NARRATION PART TWO",
                    "100.00",
                    "900.00 CR",
                    "TELEPHONE NO. 0112 000 000",
                ]
            )
        ]
    )

    assert parsed.transactions[0].description == "SYNTHETIC LONG NARRATION PART TWO"


def test_identification():
    commercial = to_pages(commercial_lines())
    assert adapter.identify(commercial) >= 0.8
    assert adapter.identify(to_pages(boc_lines())) == 0.0
    assert adapter.identify(to_pages(hnb_lines())) == 0.0
    assert select_adapter(commercial).code == "commercial"
    assert select_adapter(to_pages(boc_lines())).code == "boc"
    assert select_adapter(to_pages(hnb_lines())).code == "hnb"


@pytest.mark.parametrize("one_line_dates", [True, False])
def test_the_quarterly_layout_reconciles(one_line_dates):
    parsed = adapter.parse(
        to_pages(commercial_quarterly_lines(account=FAKE_ACCOUNT, one_line_dates=one_line_dates))
    )

    assert parsed.statement_date == date(2026, 9, 30)
    assert parsed.period_start == date(2026, 6, 30)
    assert parsed.opening_balance == Decimal("1000.00")
    assert parsed.closing_balance == Decimal("1008.00")
    assert parsed.account_number == FAKE_ACCOUNT

    interest, tax = parsed.transactions
    assert interest.date == date(2026, 7, 31) and interest.description == "SYNTHETIC INTEREST"
    assert (interest.credit, interest.debit) == (Decimal("10.00"), Decimal("0.00"))
    assert (tax.debit, tax.credit) == (Decimal("2.00"), Decimal("0.00"))
    assert validate(parsed).reconciled is True


def test_the_quarterly_totals_and_counts_are_read_and_the_notes_are_not_rows():
    parsed = adapter.parse(to_pages(commercial_quarterly_lines()))

    assert parsed.declared_withdrawals.total == Decimal("2.00")
    assert parsed.declared_deposits.total == Decimal("10.00")
    assert parsed.declared_deposits.count == 1 and parsed.declared_withdrawals.count == 1
    declared = validate(parsed).declared
    assert declared["deposits"]["total_match"] is True
    assert declared["withdrawals"]["total_match"] is True
    # the year-to-date interest and tax notes after the closing line add no rows
    assert len(parsed.transactions) == 2


def test_a_quarterly_balance_that_does_not_add_up_is_flagged():
    parsed = adapter.parse(
        to_pages(
            commercial_quarterly_lines(
                rows=[("31 Jul 2026", "SYNTHETIC INTEREST", "10.00", "1,015.00")],
                closing=("30/09/26", "1,015.00"),
                totals=("0.00", "10.00"),
            )
        )
    )
    assert "balance_mismatch" in {issue.code for issue in parsed.issues}
    assert validate(parsed).reconciled is False


def test_the_quarterly_layout_is_identified_and_is_not_boc():
    from app.adapters.boc import BocAdapter

    pages = to_pages(commercial_quarterly_lines())
    assert adapter.identify(pages) >= 0.9
    assert BocAdapter().identify(pages) == 0.0
    assert select_adapter(pages).code == "commercial"


def test_boc_does_not_claim_a_statement_that_names_commercial_bank_of_ceylon():
    from app.adapters.boc import BocAdapter

    text = "In Account With\nCommercial Bank Of Ceylon PLC\nParticulars\nPayments\nReceipts\nBalance"
    assert BocAdapter().identify([text]) == 0.0


def test_end_to_end_with_a_real_pdf(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    with session_factory() as db:
        db.add(Bank(code="commercial", name="Commercial Bank"))
        db.commit()

    pdf = pdf_from_pages([commercial_lines(account=FAKE_ACCOUNT)])
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, pdf)

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.adapter == "commercial" and doc.bank.code == "commercial"
        assert doc.opening_balance == Decimal("1000.00")
        assert doc.closing_balance == Decimal("900.00")
        (tx,) = db.scalars(select(Transaction)).all()
        assert tx.debit == Decimal("100.00") and tx.transaction_date == date(2026, 10, 15)
