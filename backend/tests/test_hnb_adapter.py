"""HNB adapter, on synthetic statements only (no real statement, name or number)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.adapters.base import ParseError
from app.adapters.hnb import HnbAdapter
from app.adapters.registry import select_adapter
from app.models import Bank, Document, Transaction
from app.services.validation import validate

from .synthetic import FAKE_ACCOUNT, boc_lines, hnb_lines, pdf_from_pages, to_pages
from .test_extraction import run_pipeline

adapter = HnbAdapter()


def parse(**kwargs):
    return adapter.parse(to_pages(hnb_lines(**kwargs)))


def test_a_simple_statement_reconciles():
    parsed = parse(account=FAKE_ACCOUNT)

    assert parsed.opening_balance == Decimal("1000.00")
    assert parsed.closing_balance == Decimal("900.00")
    assert parsed.statement_date == date(2026, 10, 31)
    assert parsed.period_start == date(2026, 10, 1)
    assert parsed.account_number == FAKE_ACCOUNT

    (row,) = parsed.transactions
    assert row.date == date(2026, 10, 15)
    assert row.description == "SYNTHETIC SHOP PURCHASE"  # the reference number is dropped
    assert row.debit == Decimal("100.00") and row.credit == Decimal("0.00")
    assert row.balance == Decimal("900.00")
    assert validate(parsed).reconciled is True


def test_debit_and_credit_are_told_apart_by_the_balance_movement():
    parsed = parse(
        rows=[
            ("05.10.26", "SD100001", "SYNTHETIC SALARY", "2,500.00", "3,500.00"),
            ("06.10.26", "", "SYNTHETIC SHOP", "600.00", "2,900.00"),
        ],
        closing=("31-10-2026", "2,900.00"),
    )

    salary, shop = parsed.transactions
    assert (salary.credit, salary.debit) == (Decimal("2500.00"), Decimal("0.00"))
    assert (shop.debit, shop.credit) == (Decimal("600.00"), Decimal("0.00"))
    assert shop.description == "SYNTHETIC SHOP"  # no reference on this row
    assert validate(parsed).reconciled is True


def test_a_wrapped_description_is_joined_and_the_footer_is_not():
    parsed = parse(
        rows=[("15.10.26", "SD100001", ["SYNTHETIC LONG", "NARRATION PART TWO"], "100.00", "900.00")]
    )

    assert parsed.transactions[0].description == "SYNTHETIC LONG NARRATION PART TWO"
    assert "DEPOSIT INSURANCE" not in parsed.transactions[0].description.upper()


def test_statement_totals_are_read_as_declared_figures():
    parsed = parse(totals=("100.00", "0"))

    assert parsed.declared_withdrawals.total == Decimal("100.00")
    assert parsed.declared_deposits.total == Decimal("0")
    result = validate(parsed)
    assert result.declared["withdrawals"]["total_match"] is True
    assert result.declared["deposits"]["total_match"] is True


def test_a_balance_that_does_not_add_up_is_flagged():
    parsed = parse(
        rows=[("15.10.26", "SD100001", "SYNTHETIC SHOP", "100.00", "850.00")],
        closing=("31-10-2026", "850.00"),
    )

    assert "balance_mismatch" in {issue.code for issue in parsed.issues}
    assert validate(parsed).reconciled is False


def test_a_statement_without_a_closing_line_cannot_be_parsed():
    with pytest.raises(ParseError) as error:
        adapter.parse(to_pages(hnb_lines(closing=None)))
    assert error.value.code == "statement_date_not_found"


def test_a_missing_opening_balance_is_reported():
    parsed = parse(opening=None)
    assert "opening_balance_unidentified" in {issue.code for issue in parsed.issues}


def test_page_two_header_is_not_glued_onto_the_last_row_of_page_one():
    first = hnb_lines(closing=None, footer=False)
    second = [
        "2",
        "MR. SYNTHETIC PERSON",
        "NO 1 TEST ROAD COLOMBO",
        "16.10.26 SD100002 SYNTHETIC SHOP 50.00 850.00",
        "31-10-2026 850.00",
    ]
    parsed = adapter.parse(["\n".join(first), "\n".join(second)])

    descriptions = [t.description for t in parsed.transactions]
    assert descriptions == ["SYNTHETIC SHOP PURCHASE", "SYNTHETIC SHOP"]
    assert [t.page_no for t in parsed.transactions] == [1, 2]
    assert validate(parsed).reconciled is True


def test_a_carry_forward_that_does_not_continue_is_flagged():
    first = hnb_lines(closing=None, footer=False)
    second = ["2", "17.10.26 B/F 999.00", "18.10.26 SD100003 SYNTHETIC SHOP 10.00 890.00", "31-10-2026 890.00"]
    parsed = adapter.parse(["\n".join(first), "\n".join(second)])

    assert "carry_forward_mismatch" in {issue.code for issue in parsed.issues}
    assert parsed.opening_balance == Decimal("1000.00")  # a later B/F never replaces it


def test_identification():
    hnb = to_pages(hnb_lines())
    assert adapter.identify(hnb) >= 0.9
    assert adapter.identify(to_pages(boc_lines())) == 0.0
    assert select_adapter(hnb).code == "hnb"
    assert select_adapter(to_pages(boc_lines())).code == "boc"


def test_end_to_end_with_a_real_pdf(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    with session_factory() as db:
        db.add(Bank(code="hnb", name="Hatton National Bank"))
        db.commit()

    pdf = pdf_from_pages([hnb_lines(account=FAKE_ACCOUNT)])
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, pdf, bank_code="hnb")

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.adapter == "hnb" and doc.bank.code == "hnb"
        assert doc.opening_balance == Decimal("1000.00")
        assert doc.closing_balance == Decimal("900.00")
        (tx,) = db.scalars(select(Transaction)).all()
        assert tx.debit == Decimal("100.00") and tx.transaction_date == date(2026, 10, 15)
