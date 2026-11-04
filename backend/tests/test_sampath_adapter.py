"""Sampath adapter, on synthetic statements only (no real statement, name or number)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.adapters.base import ParseError
from app.adapters.boc import BocAdapter
from app.adapters.commercial import CommercialAdapter
from app.adapters.hnb import HnbAdapter
from app.adapters.registry import select_adapter
from app.adapters.sampath import SampathAdapter
from app.models import Bank, Document, Transaction
from app.services.validation import validate

from .synthetic import (
    FAKE_ACCOUNT,
    boc_lines,
    commercial_lines,
    commercial_quarterly_lines,
    hnb_lines,
    pdf_from_pages,
    sampath_lines,
    to_pages,
)
from .test_extraction import run_pipeline

adapter = SampathAdapter()


def parse(**kwargs):
    return adapter.parse(to_pages(sampath_lines(**kwargs)))


def test_a_simple_statement_reconciles():
    parsed = parse(account=FAKE_ACCOUNT)

    assert parsed.opening_balance == Decimal("1000.00")
    assert parsed.closing_balance == Decimal("900.00")
    assert parsed.period_start == date(2025, 12, 22)
    assert parsed.statement_date == date(2025, 12, 31)  # the period end, not the print date
    assert parsed.account_number == FAKE_ACCOUNT

    (row,) = parsed.transactions
    assert row.date == date(2025, 12, 23)
    assert row.description == "SYNTHETIC SHOP"  # the branch code NSC is dropped
    assert row.debit == Decimal("100.00") and row.credit == Decimal("0.00")
    assert row.balance == Decimal("900.00")
    assert validate(parsed).reconciled is True


def test_a_zero_opening_balance_has_no_suffix_and_a_deposit_is_a_credit():
    parsed = parse(
        opening=("22DEC2025", "0.00"),
        rows=[
            ("22Dec25", "JAFFNA", "CDK 213758", "5,000.00", "5,000.00Cr"),
            ("23Dec25", "H/O", "Fee:SET-Card 413", "250.00", "4,750.00Cr"),
        ],
        closing=("31Dec2025", "4,750.00Cr"),
    )

    assert parsed.opening_balance == Decimal("0.00")
    deposit, fee = parsed.transactions
    assert deposit.description == "CDK 213758" and deposit.credit == Decimal("5000.00")
    assert fee.description == "Fee:SET-Card 413" and fee.debit == Decimal("250.00")
    assert validate(parsed).reconciled is True


def test_a_debit_balance_is_negative():
    parsed = parse(
        opening=("22DEC2025", "100.00Cr"),
        rows=[("23Dec25", "NSC", "SYNTHETIC SHOP", "250.00", "150.00Dr")],
        closing=("31Dec2025", "150.00Dr"),
    )

    (row,) = parsed.transactions
    assert row.balance == Decimal("-150.00") and row.debit == Decimal("250.00")
    assert parsed.closing_balance == Decimal("-150.00")
    assert validate(parsed).reconciled is True


def test_statement_totals_are_read_as_declared_figures():
    parsed = parse(totals=("100.00", "0.00"))

    assert parsed.declared_withdrawals.total == Decimal("100.00")
    assert parsed.declared_deposits.total == Decimal("0.00")
    declared = validate(parsed).declared
    assert declared["withdrawals"]["total_match"] is True
    assert declared["deposits"]["total_match"] is True


def test_a_balance_that_does_not_add_up_is_flagged():
    parsed = parse(
        rows=[("23Dec25", "NSC", "SYNTHETIC SHOP", "100.00", "850.00Cr")],
        closing=("31Dec2025", "850.00Cr"),
    )

    assert "balance_mismatch" in {issue.code for issue in parsed.issues}
    assert validate(parsed).reconciled is False


def test_a_statement_without_a_period_cannot_be_parsed():
    with pytest.raises(ParseError) as error:
        adapter.parse(to_pages(sampath_lines(period=None)))
    assert error.value.code == "statement_date_not_found"


def test_missing_opening_and_closing_balances_are_reported():
    parsed = parse(opening=None, closing=None)
    codes = {issue.code for issue in parsed.issues}
    assert {"opening_balance_unidentified", "closing_balance_unidentified"} <= codes


def test_header_text_on_a_later_page_is_not_glued_onto_a_row():
    first = sampath_lines(closing=None)
    second = [
        "TO:",
        "MR. SYNTHETIC PERSON",
        f"{FAKE_ACCOUNT} LKR PAGE_NO: 2",
        "FOR THE PERIOD : 22-12-2025 to 31-12-2025 DATE: 01-01-2026",
        "23DEC2025 B/F 900.00Cr",
        "24Dec25 NSC SYNTHETIC SHOP 50.00 850.00Cr",
        "31Dec2025 C/F 850.00Cr",
    ]
    parsed = adapter.parse(["\n".join(first), "\n".join(second)])

    assert [t.description for t in parsed.transactions] == ["SYNTHETIC SHOP", "SYNTHETIC SHOP"]
    assert [t.page_no for t in parsed.transactions] == [1, 2]
    assert parsed.opening_balance == Decimal("1000.00")  # a later B/F never replaces it
    assert parsed.closing_balance == Decimal("850.00")
    assert validate(parsed).reconciled is True


def test_a_carry_forward_that_does_not_continue_is_flagged():
    first = sampath_lines(closing=None)
    second = ["23DEC2025 B/F 999.00Cr", "24Dec25 NSC SYNTHETIC SHOP 9.00 990.00Cr", "31Dec2025 C/F 990.00Cr"]
    parsed = adapter.parse(["\n".join(first), "\n".join(second)])

    assert "carry_forward_mismatch" in {issue.code for issue in parsed.issues}


def test_identification_and_no_other_bank_claims_it():
    sampath = to_pages(sampath_lines())
    assert adapter.identify(sampath) >= 0.8
    for other in (BocAdapter(), HnbAdapter(), CommercialAdapter()):
        assert other.identify(sampath) == 0.0
    assert select_adapter(sampath).code == "sampath"

    for pages, code in (
        (to_pages(boc_lines()), "boc"),
        (to_pages(hnb_lines()), "hnb"),
        (to_pages(commercial_lines()), "commercial"),
        (to_pages(commercial_quarterly_lines()), "commercial"),
    ):
        assert adapter.identify(pages) == 0.0
        assert select_adapter(pages).code == code


def test_end_to_end_with_a_real_pdf(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    with session_factory() as db:
        db.add(Bank(code="sampath", name="Sampath Bank"))
        db.commit()

    pdf = pdf_from_pages([sampath_lines(account=FAKE_ACCOUNT)])
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, pdf)

    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.status == "reconciled"
        assert doc.adapter == "sampath" and doc.bank.code == "sampath"
        assert doc.opening_balance == Decimal("1000.00")
        assert doc.closing_balance == Decimal("900.00")
        (tx,) = db.scalars(select(Transaction)).all()
        assert tx.debit == Decimal("100.00") and tx.transaction_date == date(2025, 12, 23)
