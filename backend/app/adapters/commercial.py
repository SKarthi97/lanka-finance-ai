"""Commercial Bank of Ceylon adapter, account statements ("Statement of Account").

Two layouts are read, both as PyMuPDF extracts them (one value per line; logos and, in the
first layout, the title, headings and footer are images and so not in the text layer).

Layout A (short statement):

    99/99/99                      header: statement date
    LKR                           currency
    9999999999                    account number (standalone, 9-16 digits)
    PAGE 1 OF 1
    01/04/26 / OPENING BALANCE / 1,000.00 CR
    30/04/26 / INTEREST / 10.00 / 1,010.00 CR        date, particulars, ONE amount, balance
    30/06/26 / CLOSING BALANCE / 1,000.00 CR
    TOTAL DEPOSITS - 3 ITEMS / 30.00                 declared totals (value follows the label)

Layout B (quarterly statement, bare balances without CR):

    STATEMENT DATE 30/09/26
    ACCOUNT NO 9999999999
    CURRENCY LKR
    1,000.00                                  opening balance figure ...
    BALANCE AS OF 30/06/26                    ... printed BEFORE its label
    31 Jul 2026  (and again, or on one line: posting date, effective date)
    INTEREST / 10.00 / 1,010.00               particulars, ONE amount, balance
    CLOSING BALANCE AS OF 30/09/26
    30.00 / 12.00 / 1,000.00                  payments total, receipts total, closing balance
    TOTAL DEPOSITS 3 ITEMS / TOTAL WITHDRAWALS 3 ITEMS     counts only
    (year-to-date interest and tax notes follow; never read as rows)

A row holds one amount, so debit vs credit is decided from the running-balance movement and
then checked by the validation layer, as for BOC and HNB. A CR/DR suffix makes a balance
positive/negative; a bare balance is positive. A date followed by the currency is a page
header, not a row. In layout B the two totals after the closing label are taken in column
order (payments, then receipts); the validation output shows whether they match the rows.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.adapters.base import (
    DeclaredTotals,
    Issue,
    ParsedStatement,
    ParsedTransaction,
    ParseError,
)

CODE = "commercial"
VERSION = "2"

_AMOUNT_TEXT = r"(?:\d[\d,]*)?\.\d{2}"
_AMOUNT = re.compile(rf"^{_AMOUNT_TEXT}$")
_BALANCE = re.compile(rf"^({_AMOUNT_TEXT})\s*(CR|DR)$", re.IGNORECASE)
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})$")
_LONG = r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})"
# "31 Jul 2026" (posting date), optionally followed on the same line by the effective date.
_LONG_DATE = re.compile(rf"^{_LONG}(?:\s+\d{{1,2}}\s+[A-Za-z]{{3}}\s+\d{{4}})?$")
_STATEMENT_DATE = re.compile(r"^STATEMENT\s+DATE\s+(\d{2})/(\d{2})/(\d{2})$", re.IGNORECASE)
_OPENING_AS_OF = re.compile(r"^BALANCE\s+AS\s+(?:OF|AT)\s+(\d{2})/(\d{2})/(\d{2})$", re.IGNORECASE)
_CLOSING_AS_OF = re.compile(
    r"^CLOSING\s+BALANCE\s+AS\s+(?:OF|AT)\s+(\d{2})/(\d{2})/(\d{2})$", re.IGNORECASE
)
_TOTAL_LABEL = re.compile(r"^TOTAL\s+(DEPOSITS|WITHDRAWALS)\s*-?\s*(\d+)\s*ITEMS?$", re.IGNORECASE)
_TOTAL_VALUE = re.compile(r"^(?:\d[\d,]*(?:\.\d{2})?|\.\d{2})$")
_PAGE = re.compile(r"^PAGE\s+\d+(?:\s+OF\s+\d+)?$", re.IGNORECASE)
_ACCOUNT = re.compile(r"(?<![\d,.])\d{9,16}(?![\d,.])")
_CURRENCIES = {"LKR", "USD", "EUR", "GBP"}
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_STOP_PREFIXES = (
    "THE ITEMS AND BALANCE",
    "BALANCE INDICATED MAY",
    "TELEPHONE NO",
    "COMMERCIAL BANK",
    "FEES WILL BE LEVIED",
)
_OPENING = "OPENING BALANCE"
_CLOSING = "CLOSING BALANCE"
_CARRY_WORDS = {
    "BALANCE B/F",
    "BALANCE C/F",
    "B/F",
    "C/F",
    "BALANCE BROUGHT FORWARD",
    "BALANCE CARRIED FORWARD",
}

_CENTS = Decimal("0.01")


def _money(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        return None


def _signed_balance(match: re.Match) -> Decimal | None:
    value = _money(match.group(1))
    if value is None:
        return None
    return -value if match.group(2).upper() == "DR" else value


def _lines(page: str) -> list[str]:
    return [line.strip() for line in page.splitlines() if line.strip()]


def _slash_date(match: re.Match) -> date | None:
    try:
        return date(2000 + int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _is_header_date(lines: list[str], index: int) -> bool:
    """A dd/mm/yy directly followed by the currency is layout A's page header."""
    return (
        _DATE.match(lines[index]) is not None
        and index + 1 < len(lines)
        and lines[index + 1].upper() in _CURRENCIES
    )


def _row_date(lines: list[str], index: int) -> tuple[int, int, int] | None:
    """(day, month, year) when this line starts a transaction row, else None."""
    text = lines[index]
    match = _DATE.match(text)
    if match:
        if _is_header_date(lines, index):
            return None
        return int(match.group(1)), int(match.group(2)), 2000 + int(match.group(3))
    long = _LONG_DATE.match(text)
    if long and long.group(2).upper() in _MONTHS:
        return int(long.group(1)), _MONTHS[long.group(2).upper()], int(long.group(3))
    return None


def _scan(pages: list[str]) -> tuple[date | None, date | None]:
    """(statement date from the header, date of the closing row)."""
    header = closing = None
    for page in pages:
        lines = _lines(page)
        for index, text in enumerate(lines):
            if header is None:
                stated = _STATEMENT_DATE.match(text)
                if stated:
                    header = _slash_date(stated)
                elif _is_header_date(lines, index):
                    header = _slash_date(_DATE.match(text))
            as_of = _CLOSING_AS_OF.match(text)
            if as_of:
                closing = _slash_date(as_of)
            elif (
                _DATE.match(text)
                and index + 1 < len(lines)
                and lines[index + 1].upper() == _CLOSING
            ):
                closing = _slash_date(_DATE.match(text))
    return header, closing


def _find_account_number(pages: list[str]) -> str | None:
    """A standalone 9-16 digit number in the first page's header, above the first row.

    The label may be an image, so only the shape of the number can be used. Returns digits
    only; callers reduce it to last4 + fingerprint at once.
    """
    lines = _lines(pages[0]) if pages else []
    for index, text in enumerate(lines):
        if _row_date(lines, index) is not None:
            break
        found = _ACCOUNT.search(text)
        if found:
            return found.group(0)
    return None


@dataclass
class _Open:
    page_no: int
    day: int
    month: int
    year: int
    lines: list[str]


class CommercialAdapter:
    code = CODE
    name = "Commercial Bank"
    version = VERSION

    def identify(self, pages: list[str]) -> float:
        lines = [line for page in pages for line in _lines(page)]
        upper = [line.upper() for line in lines]
        score = 0.0
        if any(_BALANCE.match(line) for line in lines):
            score += 0.4
        if _OPENING in upper or any(_OPENING_AS_OF.match(line) for line in lines):
            score += 0.2
        if _CLOSING in upper or any(_CLOSING_AS_OF.match(line) for line in lines):
            score += 0.2
        if any(_TOTAL_LABEL.match(line) for line in lines):
            score += 0.2
        if any("COMMERCIAL BANK" in line for line in upper):
            score += 0.5
        return min(score, 1.0)

    def parse(self, pages: list[str]) -> ParsedStatement:
        header_date, closing_date = _scan(pages)
        statement_date = header_date or closing_date
        if statement_date is None:
            raise ParseError("statement_date_not_found")

        statement = ParsedStatement(
            bank_code=CODE,
            adapter=CODE,
            adapter_version=VERSION,
            statement_date=statement_date,
            period_start=None,
            opening_balance=None,
            closing_balance=None,
            account_number=_find_account_number(pages),
        )
        builder = _Builder(statement)

        for page_no, page in enumerate(pages, start=1):
            lines = _lines(page)
            current: _Open | None = None
            pending_total: tuple[str, int] | None = None
            for index, text in enumerate(lines):
                awaiting, pending_total = pending_total, None  # a value must follow its label at once

                started = _row_date(lines, index)
                if started is not None:
                    if current is not None and not current.lines:
                        continue  # the effective date straight after the posting date
                    builder.flush(current)
                    current = _Open(page_no, *started, [])
                    continue
                if _is_header_date(lines, index):
                    builder.flush(current)
                    current = None
                    continue

                label = _TOTAL_LABEL.match(text)
                if label:
                    builder.flush(current)
                    current = None
                    kind, count = label.group(1).upper(), int(label.group(2))
                    builder.declare(kind, count, None)
                    pending_total = (kind, count)
                    continue

                if awaiting is not None and _TOTAL_VALUE.match(text):
                    builder.declare(awaiting[0], awaiting[1], text)
                    continue

                opening = _OPENING_AS_OF.match(text)
                if opening:
                    builder.flush(current)
                    current = None
                    when = _slash_date(opening)
                    previous = lines[index - 1] if index else ""
                    if when is not None:
                        builder.set_opening(_money(previous) if _AMOUNT.match(previous) else None, when, page_no)
                    continue

                closing = _CLOSING_AS_OF.match(text)
                if closing:
                    builder.flush(current)
                    current = _Open(
                        page_no, int(closing.group(1)), int(closing.group(2)), 2000 + int(closing.group(3)), [_CLOSING]
                    )
                    continue

                if _PAGE.match(text) or text.upper().startswith(_STOP_PREFIXES):
                    builder.flush(current)  # page number, footer
                    current = None
                    continue

                if current is not None:
                    is_figure = _AMOUNT.match(text) or _BALANCE.match(text)
                    if current.lines and current.lines[0] == _CLOSING and not is_figure:
                        builder.flush(current)  # the notes after the closing figures
                        current = None
                        continue
                    current.lines.append(text)
            builder.flush(current)

        builder.finish()
        return statement


class _Builder:
    def __init__(self, statement: ParsedStatement) -> None:
        self.statement = statement
        self.previous_balance: Decimal | None = None
        self.seen_opening = False
        self.seen_closing = False
        self.seq = 0

    def declare(self, kind: str, count: int | None, value: str | Decimal | None) -> None:
        total = _money(value) if isinstance(value, str) else value
        existing = self.statement.declared_deposits if kind == "DEPOSITS" else self.statement.declared_withdrawals
        merged = DeclaredTotals(
            count=count if count is not None else (existing.count if existing else None),
            total=total if total is not None else (existing.total if existing else None),
        )
        if kind == "DEPOSITS":
            self.statement.declared_deposits = merged
        else:
            self.statement.declared_withdrawals = merged

    def set_opening(self, balance: Decimal | None, when: date, page_no: int) -> None:
        if self.seen_opening:
            return
        self.seen_opening = True
        if balance is None:
            self.statement.issues.append(Issue("opening_balance_unidentified", page_no))
            return
        self.statement.opening_balance = balance
        self.statement.period_start = when
        self.previous_balance = balance

    def flush(self, row: _Open | None) -> None:
        if row is None:
            return
        statement = self.statement

        description_parts: list[str] = []
        amounts: list[Decimal] = []
        balance: Decimal | None = None
        for text in row.lines:
            matched = _BALANCE.match(text)
            if matched:
                balance = _signed_balance(matched)
            elif _AMOUNT.match(text):
                value = _money(text)
                if value is not None:
                    amounts.append(value)
            else:
                description_parts.append(text)
        description = " ".join(description_parts).strip()
        upper = description.upper()

        try:
            row_date = date(row.year, row.month, row.day)
        except ValueError:
            statement.issues.append(Issue("invalid_date", row.page_no))
            return

        if upper == _OPENING:
            if balance is None and amounts:
                balance = amounts[-1]
            self.set_opening(balance, row_date, row.page_no)
            return

        if upper == _CLOSING:
            self.seen_closing = True
            if balance is None and amounts:
                balance = amounts[-1]
                if len(amounts) >= 3:  # payments total, receipts total, closing balance
                    self.declare("WITHDRAWALS", None, amounts[-3])
                    self.declare("DEPOSITS", None, amounts[-2])
            if balance is None:
                statement.issues.append(Issue("closing_balance_unidentified", row.page_no))
            else:
                statement.closing_balance = balance
            return

        if upper in _CARRY_WORDS or not description:
            return  # page carry-forward, not a transaction

        if balance is None and len(amounts) == 2:
            balance = amounts.pop()  # bare balance: the last figure on the row
        if len(amounts) != 1 or balance is None:
            statement.issues.append(Issue("unexpected_amount_columns", row.page_no))
            return

        amount = amounts[0]
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
        statement.transactions.append(
            ParsedTransaction(
                seq=self.seq,
                page_no=row.page_no,
                date=row_date,
                description=description,
                debit=debit.quantize(_CENTS),
                credit=credit.quantize(_CENTS),
                balance=balance.quantize(_CENTS),
            )
        )
        if issue_code:
            statement.issues.append(Issue(issue_code, row.page_no, self.seq))
        self.previous_balance = balance

    def finish(self) -> None:
        if not self.seen_opening:
            self.statement.issues.append(Issue("opening_balance_unidentified"))
        if not self.seen_closing:
            self.statement.issues.append(Issue("closing_balance_unidentified"))
