"""Bank of Ceylon adapter.

Ported from the prototype parser (src/parsers/boc_parser.py), which works on the text
PyMuPDF extracts from BOC's computer-generated statements: one table cell per line.
Differences from the prototype: exact Decimal arithmetic, page numbers per row,
repeated column headers and page footers ignored, issue codes instead of free text.

Debit vs credit is decided from the running balance movement; the validation layer
then checks that the amount equals the balance change.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.adapters.base import (
    DeclaredTotals,
    Issue,
    ParsedStatement,
    ParsedTransaction,
    ParseError,
)

CODE = "boc"
VERSION = "1"

_STATEMENT_DATE = re.compile(r"DATE:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
# BOC prints a zero as ".00" (no leading digit), e.g. an opening balance of nil.
_AMOUNT = re.compile(r"^\(?-?(?:\d[\d,]*)?\.\d{2}\)?$")
_PAGE_FOOTER = re.compile(r"^PAGE\s+\d+(\s+OF\s+\d+)?$", re.IGNORECASE)
_COLUMN_HEADERS = {"PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE", "DATE"}
_REQUIRED_HEADERS = ("PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE")

# "A/C No: 0000000000" on one line, or the label alone with the number on the next line.
_ACCOUNT_INLINE = re.compile(
    r"(?:A/?C|ACCOUNT)\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*(\d[\d\- ]{4,22}\d)\b", re.IGNORECASE
)
_ACCOUNT_LABEL = re.compile(
    r"^(?:A/?C|ACCOUNT)\s*(?:NO\.?|NUMBER)?\s*[:\-]?$", re.IGNORECASE
)
_DIGITS = re.compile(r"^\d[\d\- ]{4,22}\d$")

_CENTS = Decimal("0.01")

# Closing summary: "TOTAL DEPOSITS", "52 item(s)", "<amount>" (cells or one line).
_TOTAL_MARKERS = {
    "TOTAL DEPOSITS": "deposits",
    "TOTAL WITHDRAWALS": "withdrawals",
    "TOTAL UNREALIZED CHEQUES": "unrealized",
}
_ITEMS = re.compile(r"(\d[\d,]*)\s*item", re.IGNORECASE)
_AMOUNT_TOKEN = re.compile(r"(?:\d[\d,]*)?\.\d{2}")
_TOTAL_LOOKAHEAD = 4  # lines after a TOTAL marker that may hold its count and amount


def _total_marker(upper_line: str) -> str | None:
    for marker, name in _TOTAL_MARKERS.items():
        if marker in upper_line:
            return name
    return None


def _absorb_declared(statement: ParsedStatement, which: str, text: str) -> None:
    """Pick the item count and amount out of a line near a TOTAL marker."""
    if which == "unrealized":
        return
    items = _ITEMS.search(text)
    amounts = _AMOUNT_TOKEN.findall(text)
    if not items and not amounts:
        return

    attribute = "declared_deposits" if which == "deposits" else "declared_withdrawals"
    declared = getattr(statement, attribute) or DeclaredTotals()
    if items and declared.count is None:
        declared.count = int(items.group(1).replace(",", ""))
    if amounts and declared.total is None:
        declared.total = _money(amounts[-1])
    setattr(statement, attribute, declared)


def _money(text: str) -> Decimal | None:
    value = text.strip().replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.replace("(", "").replace(")", "")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _assign_years(day_months: list[tuple[int, int]], statement_date: date) -> list[int]:
    """Years for DD/MM dates listed oldest first, found by walking back from the end.

    Statement rows are chronological and the statement ends on `statement_date`, so the
    last row is in that year. Going backwards, the year drops by one whenever the date
    jumps forward in the calendar (e.g. a December row before a January row). This works
    for statements spanning many years, where the printed dates carry no year.
    """
    years = [0] * len(day_months)
    year = statement_date.year
    later = (statement_date.month, statement_date.day)
    for index in range(len(day_months) - 1, -1, -1):
        day, month = day_months[index]
        if (month, day) > later:
            year -= 1
        years[index] = year
        later = (month, day)
    return years


def _find_account_number(lines: list[tuple[int, str]]) -> str | None:
    """Best effort. Returns digits only, or None.

    Only the header area is searched (page 1, before the first transaction date line),
    so account numbers quoted inside transaction descriptions are never picked up.
    """
    header: list[str] = []
    for page_no, text in lines:
        if page_no != lines[0][0] or _DAY_MONTH.fullmatch(text):
            break
        header.append(text)

    for index, text in enumerate(header):
        inline = _ACCOUNT_INLINE.search(text)
        if inline:
            return re.sub(r"\D", "", inline.group(1))
        if _ACCOUNT_LABEL.match(text) and index + 1 < len(header):
            following = header[index + 1]
            if _DIGITS.match(following):
                return re.sub(r"\D", "", following)
    return None


class BocAdapter:
    code = CODE
    name = "Bank of Ceylon"
    version = VERSION

    def identify(self, pages: list[str]) -> float:
        text = "\n".join(pages).upper()
        if not all(header in text for header in _REQUIRED_HEADERS):
            return 0.0
        score = 0.5
        if "BANK OF CEYLON" in text:
            score += 0.3
        if "BALANCE B/F" in text:
            score += 0.2
        return min(score, 1.0)

    def parse(self, pages: list[str]) -> ParsedStatement:
        full_text = "\n".join(pages)

        match = _STATEMENT_DATE.search(full_text)
        if not match:
            raise ParseError("statement_date_not_found")
        try:
            statement_date = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        except ValueError:
            raise ParseError("statement_date_invalid") from None

        upper = full_text.upper()
        if not all(header in upper for header in _REQUIRED_HEADERS):
            raise ParseError("format_mismatch")

        lines: list[tuple[int, str]] = []
        first_page_header: set[str] = set()
        for page_no, page_text in enumerate(pages, start=1):
            seen_first_date = False
            for raw in page_text.splitlines():
                text = raw.strip()
                if not text:
                    continue
                if text.upper() in _COLUMN_HEADERS or _PAGE_FOOTER.match(text):
                    continue  # repeated per-page headers / footers
                if _DAY_MONTH.fullmatch(text):
                    seen_first_date = True
                if page_no == 1:
                    if not seen_first_date:
                        first_page_header.add(text)
                elif text in first_page_header and not (
                    _AMOUNT.fullmatch(text) or _DAY_MONTH.fullmatch(text)
                ):
                    # Page 1's header (name, address, titles) repeated on a later page.
                    # Without this it would be glued onto the previous row's description.
                    continue
                lines.append((page_no, text))

        statement = ParsedStatement(
            bank_code=CODE,
            adapter=CODE,
            adapter_version=VERSION,
            statement_date=statement_date,
            period_start=None,
            opening_balance=None,
            closing_balance=None,
            account_number=_find_account_number(lines) if lines else None,
        )

        state = _State(statement)
        reading_closing = False
        capturing: str | None = None
        capture_left = 0

        for page_no, text in lines:
            upper_line = text.upper()

            if _DAY_MONTH.fullmatch(text):
                state.flush()
                state.start(text, page_no)
                reading_closing = False
                continue

            if "BALANCE C/F" in upper_line:
                state.flush()
                state.reset()
                reading_closing = True
                continue

            if reading_closing:
                if _AMOUNT.fullmatch(text):
                    statement.closing_balance = _money(text)
                    reading_closing = False
                continue

            marker = _total_marker(upper_line)
            if marker:
                state.flush()
                state.reset()
                capturing, capture_left = marker, _TOTAL_LOOKAHEAD
                _absorb_declared(statement, marker, text)  # figures on the label's own line
                continue

            if capturing and capture_left > 0:
                _absorb_declared(statement, capturing, text)
                capture_left -= 1
                continue

            if state.date_text:
                state.lines.append(text)

        state.flush()
        state.finish()
        return statement


class _State:
    """Groups lines into date-led blocks and turns each block into a transaction."""

    def __init__(self, statement: ParsedStatement) -> None:
        self.statement = statement
        self.date_text: str | None = None
        self.page_no = 1
        self.lines: list[str] = []
        self.previous_balance: Decimal | None = None
        self.seen_b_f = False
        self.opening_day_month: tuple[int, int] | None = None
        self.rows: list[_Row] = []
        self.seq = 0

    def start(self, date_text: str, page_no: int) -> None:
        self.date_text = date_text
        self.page_no = page_no
        self.lines = []

    def reset(self) -> None:
        self.date_text = None
        self.lines = []

    def flush(self) -> None:
        if not self.date_text:
            return

        statement = self.statement
        amounts: list[Decimal] = []
        before_amounts: list[str] = []
        after_amounts: list[str] = []
        for line in self.lines:
            if _AMOUNT.fullmatch(line):
                amount = _money(line)
                if amount is not None:
                    amounts.append(amount)
            else:
                (after_amounts if amounts else before_amounts).append(line)

        # A row reads: date, description (possibly wrapped), then amounts. Text after the
        # amounts is page furniture (footer, next page's header, end-of-statement notes)
        # that landed in the same block, so it is not part of the description. Rows whose
        # text only appears after the amounts keep the old behaviour as a fallback.
        description = " ".join(before_amounts or after_amounts).strip()
        upper = description.upper()
        date_text, page_no = self.date_text, self.page_no
        day, month = (int(part) for part in date_text.split("/"))
        self.reset()

        if not description:
            return

        if "BALANCE B/F" in upper:
            if not self.seen_b_f:
                # The FIRST B/F line is the opening balance. If it cannot be read, a
                # later page's carry-forward must not stand in for it.
                self.seen_b_f = True
                if not amounts:
                    statement.issues.append(Issue("opening_balance_unidentified", page_no))
                else:
                    if len(amounts) > 1:
                        # The balance column is the rightmost. Reconciliation still
                        # decides whether this reading was right.
                        statement.issues.append(Issue("opening_balance_ambiguous", page_no))
                    statement.opening_balance = amounts[-1]
                    self.previous_balance = amounts[-1]
                    self.opening_day_month = (day, month)  # year is resolved in finish()
            elif amounts and amounts[-1] != self.previous_balance:
                # A page carry-forward must continue exactly where the last row ended.
                # It never replaces the statement's opening balance.
                statement.issues.append(Issue("carry_forward_mismatch", page_no))
            return

        # Statement summary lines are not transactions.
        if "TOTAL " in upper or "UNREALIZED CHEQUES" in upper:
            return

        if len(amounts) != 2:
            statement.issues.append(Issue("unexpected_amount_columns", page_no))
            return

        amount, balance = amounts
        if amount < 0:
            statement.issues.append(Issue("negative_amount", page_no))
            return

        debit = credit = Decimal("0.00")
        issue_code: str | None = None

        if self.previous_balance is None:
            issue_code = "opening_balance_unavailable"
        else:
            movement = balance - self.previous_balance
            if movement > 0:
                credit = amount
            elif movement < 0:
                debit = amount
            else:
                issue_code = "no_balance_movement"
            if abs(abs(movement) - amount) > Decimal("0.02"):
                issue_code = "balance_mismatch"

        self.seq += 1
        self.rows.append(
            _Row(
                seq=self.seq,
                page_no=page_no,
                day=day,
                month=month,
                description=description,
                debit=debit.quantize(_CENTS),
                credit=credit.quantize(_CENTS),
                balance=balance.quantize(_CENTS),
            )
        )
        if issue_code:
            statement.issues.append(Issue(issue_code, page_no, self.seq))

        self.previous_balance = balance

    def finish(self) -> None:
        """Resolve every date's year at once (needs the whole statement), then build rows."""
        statement = self.statement
        dated = ([self.opening_day_month] if self.opening_day_month else []) + [
            (row.day, row.month) for row in self.rows
        ]
        years = _assign_years(dated, statement.statement_date)

        if self.opening_day_month:
            day, month = self.opening_day_month
            try:
                statement.period_start = date(years[0], month, day)
            except ValueError:
                statement.issues.append(Issue("invalid_date"))
            years = years[1:]

        for row, year in zip(self.rows, years):
            try:
                row_date = date(year, row.month, row.day)
            except ValueError:
                statement.issues.append(Issue("invalid_date", row.page_no, row.seq))
                continue
            statement.transactions.append(
                ParsedTransaction(
                    seq=row.seq,
                    page_no=row.page_no,
                    date=row_date,
                    description=row.description,
                    debit=row.debit,
                    credit=row.credit,
                    balance=row.balance,
                )
            )


@dataclass
class _Row:
    seq: int
    page_no: int
    day: int
    month: int
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
