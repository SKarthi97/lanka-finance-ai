from decimal import Decimal

from app.adapters.boc import BocAdapter
from app.services.validation import validate

from .synthetic import boc_lines, to_pages

adapter = BocAdapter()


def check(**kwargs):
    return validate(adapter.parse(to_pages(boc_lines(**kwargs))))


def codes(result):
    return [issue.code for issue in result.issues]


def test_consistent_statement_reconciles_with_full_confidence():
    result = check()
    assert result.reconciled is True
    assert result.confidence == 1.0
    assert result.row_status == {1: "ok"}
    assert result.checks["statement_reconciliation"] == {"passed": 1, "failed": 0}
    assert result.checks["row_balance"] == {"passed": 1, "failed": 0}


def test_wrong_closing_balance_fails_reconciliation():
    result = check(closing="999.00")
    assert result.reconciled is False
    assert "statement_not_reconciled" in codes(result)
    assert result.confidence <= 0.5


def test_row_balance_mismatch_is_flagged_on_that_row():
    result = check(rows=[("05/09", "ODD ROW", "100.00", "850.00")], closing="850.00")
    assert result.reconciled is False
    assert result.row_status[1] == "balance_mismatch"
    assert "row_balance_mismatch" in codes(result)


def test_missing_opening_balance_blocks_reconciliation():
    result = check(opening=None)
    assert result.reconciled is False
    assert "opening_balance_missing" in codes(result)


def test_missing_closing_balance_blocks_reconciliation():
    result = check(closing=None)
    assert result.reconciled is False
    assert "closing_balance_missing" in codes(result)


def test_date_outside_statement_period_is_flagged():
    """Years are inferred, so the adapter itself cannot emit an out-of-range date; the
    validator still guards against one (e.g. from a future adapter)."""
    from datetime import date

    statement = adapter.parse(to_pages(boc_lines()))
    statement.transactions[0].date = date(2021, 7, 1)  # well before the period start

    result = validate(statement)
    assert result.reconciled is False
    assert "date_outside_period" in codes(result)
    assert result.row_status[1] == "needs_review"


def test_parser_issue_blocks_even_if_totals_happen_to_match():
    result = check(rows=[("05/09", "BROKEN ROW", "100.00")], closing="1,000.00")
    assert result.reconciled is False
    assert result.checks["rows_parsed"]["failed"] == 1


def test_statement_without_activity_reconciles():
    result = check(rows=[], closing="1,000.00")
    assert result.reconciled is True
    assert result.confidence == 1.0


def test_validation_output_contains_codes_not_text():
    result = check(rows=[("05/09", "SECRET MERCHANT NAME", "100.00", "850.00")], closing="850.00")
    serialised = repr([(i.code, i.page, i.seq) for i in result.issues]) + repr(result.checks)
    assert "SECRET" not in serialised


# --- implausible date jumps (mis-ordered rows) ------------------------------------------


def test_a_misordered_row_that_shifts_the_year_is_sent_to_review():
    # Rows 10/06 then 08/06: the year walk reads 10/06 as a year earlier, a ~363-day jump.
    result = check(
        statement_date="30/06/2022",
        opening=("01/06", "1,000.00"),
        rows=[
            ("10/06", "ROW A", "10.00", "990.00"),
            ("08/06", "ROW B", "10.00", "980.00"),  # out of order
            ("12/06", "ROW C", "10.00", "970.00"),
        ],
        closing="970.00",
    )
    assert result.reconciled is False  # the balances are fine; the dates are not
    assert "suspicious_date_gap" in codes(result)
    assert result.checks["date_sequence"]["failed"] == 1
    assert result.checks["statement_reconciliation"]["failed"] == 0


def test_date_gap_threshold():
    from datetime import timedelta

    def gap(days):
        statement = adapter.parse(to_pages(boc_lines()))
        statement.transactions[0].date = statement.period_start + timedelta(days=days)
        statement.statement_date = statement.transactions[0].date  # keep it in the period
        return validate(statement)

    assert "suspicious_date_gap" not in codes(gap(299))
    assert "suspicious_date_gap" in codes(gap(301))


def test_a_normal_long_statement_has_no_suspicious_gaps():
    result = check(
        statement_date="30/06/2022",
        opening=("28/12", "1,000.00"),
        rows=[
            ("31/12", "R1", "10.00", "990.00"),
            ("06/01", "R2", "10.00", "980.00"),
            ("15/06", "R3", "10.00", "970.00"),
            ("20/12", "R4", "10.00", "960.00"),
            ("10/03", "R5", "10.00", "950.00"),
            ("30/06", "R6", "10.00", "940.00"),
        ],
        closing="940.00",
    )
    assert result.reconciled is True
    assert result.checks["date_sequence"]["failed"] == 0


# --- the statement's own totals (informational) ------------------------------------------

TWO = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
]


def test_declared_totals_are_compared_with_what_was_extracted():
    result = check(rows=TWO, closing="3,000.00", summary=(1, "2,500.00", 1, "500.00"))

    assert result.declared["deposits"] == {
        "declared_count": 1,
        "found_count": 1,
        "count_match": True,
        "declared_total": "2500.00",
        "found_total": "2500.00",
        "total_match": True,
    }
    assert result.declared["withdrawals"]["count_match"] is True
    assert result.declared["withdrawals"]["total_match"] is True


def test_declared_totals_never_block_reconciliation():
    # The statement claims 52 / 240 items; we found 1 / 1. Informational only.
    result = check(rows=TWO, closing="3,000.00", summary=(52, "2,500.00", 240, "500.00"))

    assert result.reconciled is True
    assert result.declared["deposits"]["count_match"] is False
    assert result.declared["deposits"]["total_match"] is True
    assert result.declared["withdrawals"]["declared_count"] == 240


def test_a_statement_without_a_summary_has_no_declared_section():
    assert check(rows=TWO, closing="3,000.00").declared == {}


def test_summary_lines_are_not_mistaken_for_transactions():
    statement = adapter.parse(
        to_pages(boc_lines(rows=TWO, closing="3,000.00", summary=(1, "2,500.00", 1, "500.00")))
    )
    assert len(statement.transactions) == 2
    assert statement.issues == []
    assert statement.declared_deposits.count == 1
    assert statement.declared_withdrawals.total == Decimal("500.00")


def test_figures_on_the_same_line_as_the_label_are_read():
    lines = boc_lines(rows=TWO, closing="3,000.00")
    lines += ["TOTAL DEPOSITS 1 item(s) 2,500.00", "TOTAL WITHDRAWALS 1 item(s) 500.00"]
    statement = adapter.parse(to_pages(lines))

    assert (statement.declared_deposits.count, statement.declared_deposits.total) == (
        1,
        Decimal("2500.00"),
    )
    assert statement.declared_withdrawals.total == Decimal("500.00")


# --- what do the statement's totals cover? ---------------------------------------------------

THREE = [
    ("02/09", "FIRST DEBIT", "100.00", "900.00"),
    ("03/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,400.00"),
    ("04/09", "LAST DEBIT", "500.00", "2,900.00"),
]


def window(summary):
    return check(rows=THREE, closing="2,900.00", summary=summary).declared_window


def test_totals_that_cover_every_row_are_recognised():
    # 1 credit (2,500) and 2 debits (100 + 500)
    assert window((1, "2,500.00", 2, "600.00")) == {"covers": "all", "rows": 3, "from_page": 1}


def test_totals_that_cover_only_the_last_rows_are_found():
    # 1 credit and 1 debit worth 500: the last two rows only
    found = window((1, "2,500.00", 1, "500.00"))
    assert found == {"covers": "last_rows", "rows": 2, "from_page": 1}


def test_totals_that_match_no_window_say_so():
    assert window((52, "9,999.00", 240, "8,888.00")) == {
        "covers": "unknown",
        "rows": None,
        "from_page": None,
    }


def test_counts_alone_are_enough_to_find_the_window():
    # The summary lines carry item counts but no amounts: only the counts can be compared.
    found = window((1, "", 1, ""))
    assert found == {"covers": "last_rows", "rows": 2, "from_page": 1}


def test_a_statement_without_totals_has_no_window():
    assert check(rows=THREE, closing="2,900.00").declared_window is None
