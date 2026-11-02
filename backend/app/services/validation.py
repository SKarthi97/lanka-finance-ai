"""Deterministic financial validation (docs/00-architecture.md section 8).

The LLM never validates numbers. Every check here is exact Decimal arithmetic and the
output contains codes and counts only, never statement text.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from app.adapters.base import Issue, ParsedStatement

ZERO = Decimal("0.00")
DATE_TOLERANCE = timedelta(days=1)

# Parser-level problems that mean a row may be missing or wrong.
BLOCKING_PARSE_ISSUES = {
    "unexpected_amount_columns",
    "negative_amount",
    "invalid_date",
    "opening_balance_unidentified",
    "carry_forward_mismatch",
}


@dataclass
class ValidationResult:
    reconciled: bool
    confidence: float
    checks: dict[str, dict[str, int]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    row_status: dict[int, str] = field(default_factory=dict)  # seq -> status


def _check(checks: dict, name: str, passed: bool) -> None:
    entry = checks.setdefault(name, {"passed": 0, "failed": 0})
    entry["passed" if passed else "failed"] += 1


def validate(statement: ParsedStatement) -> ValidationResult:
    checks: dict[str, dict[str, int]] = {}
    issues: list[Issue] = list(statement.issues)
    row_failures: dict[int, str] = {}

    def fail_row(seq: int, page: int, code: str, status: str = "needs_review") -> None:
        issues.append(Issue(code, page, seq))
        # A balance mismatch is the more informative status; keep it if already set.
        if row_failures.get(seq) != "balance_mismatch":
            row_failures[seq] = status

    previous = statement.opening_balance
    period_start = statement.period_start

    for tx in statement.transactions:
        # 1. exactly one of debit / credit is non-zero
        one_sided = (tx.debit > ZERO) != (tx.credit > ZERO)
        _check(checks, "row_amounts", one_sided)
        if not one_sided:
            fail_row(tx.seq, tx.page_no, "row_amounts_invalid")

        # 2. running balance: previous - debit + credit == balance
        if previous is not None:
            consistent = previous - tx.debit + tx.credit == tx.balance
            _check(checks, "row_balance", consistent)
            if not consistent:
                fail_row(tx.seq, tx.page_no, "row_balance_mismatch", "balance_mismatch")
        previous = tx.balance

        # 3. date within the statement period (one day tolerance)
        if period_start is not None:
            in_period = (
                period_start - DATE_TOLERANCE
                <= tx.date
                <= statement.statement_date + DATE_TOLERANCE
            )
            _check(checks, "date_in_period", in_period)
            if not in_period:
                fail_row(tx.seq, tx.page_no, "date_outside_period")

    # Parser issues that already pinned a row keep that row flagged.
    for issue in statement.issues:
        if issue.seq is not None and issue.code in {"balance_mismatch", "no_balance_movement"}:
            row_failures.setdefault(
                issue.seq,
                "balance_mismatch" if issue.code == "balance_mismatch" else "needs_review",
            )

    # 4. statement level: opening + credits - debits == closing
    statement_ok = False
    if statement.opening_balance is None:
        issues.append(Issue("opening_balance_missing"))
        _check(checks, "statement_reconciliation", False)
    elif statement.closing_balance is None:
        issues.append(Issue("closing_balance_missing"))
        _check(checks, "statement_reconciliation", False)
    else:
        total_debit = sum((t.debit for t in statement.transactions), ZERO)
        total_credit = sum((t.credit for t in statement.transactions), ZERO)
        statement_ok = (
            statement.opening_balance + total_credit - total_debit
            == statement.closing_balance
        )
        _check(checks, "statement_reconciliation", statement_ok)
        if not statement_ok:
            issues.append(Issue("statement_not_reconciled"))

    parse_clean = not any(i.code in BLOCKING_PARSE_ISSUES for i in statement.issues)
    _check(checks, "rows_parsed", parse_clean)

    rows = len(statement.transactions)
    clean_rows = rows - len(row_failures)
    row_ratio = clean_rows / rows if rows else 1.0
    confidence = row_ratio if statement_ok and parse_clean else min(row_ratio, 0.5)

    reconciled = statement_ok and parse_clean and not row_failures

    row_status = {
        tx.seq: row_failures.get(tx.seq, "ok") for tx in statement.transactions
    }
    return ValidationResult(
        reconciled=reconciled,
        confidence=round(confidence, 3),
        checks=checks,
        issues=issues,
        row_status=row_status,
    )
