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

# Statement dates have no year, so the adapter infers it from row order. A row out of
# order makes that inference jump by about a year (a ~360-day gap between neighbours).
# Real accounts post interest or fees far more often, so a gap this long means a
# mis-dated row. It sends the statement to review; accepting it is the user's call.
MAX_ROW_GAP = timedelta(days=300)

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
    # What the statement says about its own totals vs what was extracted. Informational:
    # it never affects `reconciled`, because what the item counts cover is not yet known.
    declared: dict[str, dict] = field(default_factory=dict)
    # Which rows the statement's totals seem to cover: all of them, only the last N, or
    # no combination we can find. None when the statement prints no totals.
    declared_window: dict | None = None


def _check(checks: dict, name: str, passed: bool) -> None:
    entry = checks.setdefault(name, {"passed": 0, "failed": 0})
    entry["passed" if passed else "failed"] += 1


def _declared_comparison(statement: ParsedStatement) -> dict[str, dict]:
    credits = [t for t in statement.transactions if t.credit > ZERO]
    debits = [t for t in statement.transactions if t.debit > ZERO]
    out: dict[str, dict] = {}

    for key, declared, rows, column in (
        ("deposits", statement.declared_deposits, credits, "credit"),
        ("withdrawals", statement.declared_withdrawals, debits, "debit"),
    ):
        if declared is None:
            continue
        found_total = sum((getattr(t, column) for t in rows), ZERO)
        out[key] = {
            "declared_count": declared.count,
            "found_count": len(rows),
            "count_match": None if declared.count is None else declared.count == len(rows),
            "declared_total": None if declared.total is None else str(declared.total),
            "found_total": str(found_total),
            "total_match": None if declared.total is None else declared.total == found_total,
        }
    return out


def _fits(declared, count: int, total: Decimal) -> bool:
    if declared is None:
        return True
    if declared.count is not None and declared.count != count:
        return False
    if declared.total is not None and declared.total != total:
        return False
    return True


def _declared_window(statement: ParsedStatement) -> dict | None:
    """Find which rows the statement's own totals describe.

    The printed counts might cover every row, or only a recent stretch (for example the
    period since the last statement). Every "last N rows" window is tried against the
    declared deposit and withdrawal counts and totals; the largest match wins.
    """
    deposits, withdrawals = statement.declared_deposits, statement.declared_withdrawals
    rows = statement.transactions
    if (deposits is None and withdrawals is None) or not rows:
        return None

    credit_count = debit_count = 0
    credit_sum = debit_sum = ZERO
    best: int | None = None  # start index of the largest matching window
    for start in range(len(rows) - 1, -1, -1):
        row = rows[start]
        if row.credit > ZERO:
            credit_count += 1
            credit_sum += row.credit
        if row.debit > ZERO:
            debit_count += 1
            debit_sum += row.debit
        if _fits(deposits, credit_count, credit_sum) and _fits(withdrawals, debit_count, debit_sum):
            best = start  # keeps moving earlier, so the largest window wins

    if best is None:
        return {"covers": "unknown", "rows": None, "from_page": None}
    if best == 0:
        return {"covers": "all", "rows": len(rows), "from_page": rows[0].page_no}
    return {"covers": "last_rows", "rows": len(rows) - best, "from_page": rows[best].page_no}


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
    previous_date = period_start

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

        # 2b. consecutive dates must not jump by almost a year (mis-ordered row)
        if previous_date is not None:
            plausible = tx.date - previous_date <= MAX_ROW_GAP
            _check(checks, "date_sequence", plausible)
            if not plausible:
                fail_row(tx.seq, tx.page_no, "suspicious_date_gap")
        previous_date = tx.date

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
        declared=_declared_comparison(statement),
        declared_window=_declared_window(statement),
    )
