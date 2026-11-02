"""Bank of Ceylon adapter.

Ported from the prototype parser (src/parsers/boc_parser.py), which works on the text
PyMuPDF extracts from BOC's computer-generated statements: one table cell per line.
Differences from the prototype: exact Decimal arithmetic, page numbers per row,
repeated column headers and page footers ignored, issue codes instead of free text.

Debit vs credit is decided from the running balance movement; the validation layer
then checks that the amount equals the balance change.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.adapters.base import Issue, ParsedStatement, ParsedTransaction, ParseError

CODE = "boc"
VERSION = "1"

_STATEMENT_DATE = re.compile(r"DATE:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_AMOUNT = re.compile(r"^\(?-?\d[\d,]*\.\d{2}\)?$")
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


def _money(text: str) -> Decimal | None:
    value = text.strip().replace(",", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.replace("(", "").replace(")", "")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _resolve_date(day_month: str, statement_date: date) -> date | None:
    """DD/MM -> a date in the statement's year, or the year before if that is in the future."""
    day, month = (int(part) for part in day_month.split("/"))
    try:
        candidate = date(statement_date.year, month, day)
        if candidate > statement_date:
            candidate = date(statement_date.year - 1, month, day)
        return candidate
    except ValueError:
        return None


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
        for page_no, page_text in enumerate(pages, start=1):
            for raw in page_text.splitlines():
                text = raw.strip()
                if not text:
                    continue
                if text.upper() in _COLUMN_HEADERS or _PAGE_FOOTER.match(text):
                    continue  # repeated per-page headers / footers
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

            if (
                "TOTAL DEPOSITS" in upper_line
                or "TOTAL WITHDRAWALS" in upper_line
                or "TOTAL UNREALIZED CHEQUES" in upper_line
            ):
                state.flush()
                state.reset()
                continue

            if state.date_text:
                state.lines.append(text)

        state.flush()
        return statement


class _State:
    """Groups lines into date-led blocks and turns each block into a transaction."""

    def __init__(self, statement: ParsedStatement) -> None:
        self.statement = statement
        self.date_text: str | None = None
        self.page_no = 1
        self.lines: list[str] = []
        self.previous_balance: Decimal | None = None
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
        descriptions: list[str] = []
        for line in self.lines:
            if _AMOUNT.fullmatch(line):
                amount = _money(line)
                if amount is not None:
                    amounts.append(amount)
            else:
                descriptions.append(line)

        description = " ".join(descriptions).strip()
        upper = description.upper()
        date_text, page_no = self.date_text, self.page_no
        self.reset()

        if not description:
            return

        if "BALANCE B/F" in upper:
            if len(amounts) == 1:
                statement.opening_balance = amounts[0]
                self.previous_balance = amounts[0]
                statement.period_start = _resolve_date(date_text, statement.statement_date)
            else:
                statement.issues.append(Issue("opening_balance_unidentified", page_no))
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

        transaction_date = _resolve_date(date_text, statement.statement_date)
        if transaction_date is None:
            statement.issues.append(Issue("invalid_date", page_no))
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
        statement.transactions.append(
            ParsedTransaction(
                seq=self.seq,
                page_no=page_no,
                date=transaction_date,
                description=description,
                debit=debit.quantize(_CENTS),
                credit=credit.quantize(_CENTS),
                balance=balance.quantize(_CENTS),
            )
        )
        if issue_code:
            statement.issues.append(Issue(issue_code, page_no, self.seq))

        self.previous_balance = balance
