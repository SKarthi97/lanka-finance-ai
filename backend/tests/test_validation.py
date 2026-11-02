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
    result = check(rows=[("01/07", "WAY TOO EARLY", "100.00", "900.00")])
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
