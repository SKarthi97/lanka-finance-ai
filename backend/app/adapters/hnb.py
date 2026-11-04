"""Hatton National Bank (HNB) adapter, savings account statements.

Layout it is written for (text as PyMuPDF extracts it; the column headings and the TOTAL /
BALANCE AS AT DATE labels are images, so they are not in the text layer):

    <page number>                               header: name, address, account number, currency ...
    01.10.26 B/F 99,999.99                      opening balance (date, "B/F", balance)
    15.10.26 SD924990 DESCRIPTION 99.99 99,999.99   date, reference (optional), particulars, amount, balance
    0 99.99                                     totals: debits, credits
    31-10-2026 99,999.99                        statement date and closing balance
    HNB is a member of the SL Deposit Insurance Scheme ...

Dates carry a two-digit year. A row holds ONE amount (debit and credit are separate columns on
paper but only the filled one appears in the text), so debit vs credit is decided from the
running-balance movement and then checked by the validation layer, as for BOC.

A line with no date that follows a row on the same page is a wrapped description. Header text
at the top of a later page is never attached to the previous page's last row.
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

CODE = "hnb"
VERSION = "1"

_AMOUNT = re.compile(r"^\(?-?(?:\d[\d,]*)?\.\d{2}\)?$")
_AMOUNT_TEXT = r"(?:\d[\d,]*)?\.\d{2}"
_ROW = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})\s+(.*)$")
_CLOSING = re.compile(rf"^(\d{{2}})-(\d{{2}})-(\d{{4}})\s+({_AMOUNT_TEXT})$")
_TOTALS = re.compile(r"^(\d[\d,]*(?:\.\d{2})?)\s+(\d[\d,]*(?:\.\d{2})?)$")
_NUMBERS_ONLY = re.compile(r"^[\d,.\s]+$")
# A bank reference such as SD924990: up to four letters then at least four digits.
_REFERENCE = re.compile(r"^[A-Za-z]{0,4}\d{4,}$")
_ACCOUNT = re.compile(r"(?<![\d,.])\d{9,16}(?![\d,.])")
_STOP_PREFIXES = (
    "HNB IS A MEMBER",
    "THIS COVER",
    "THIS IS A COMPUTER",
    "HATTON NATIONAL BANK",
)
_OPENING_WORDS = {"B/F", "BALANCE B/F", "BAL B/F"}
_CARRY_WORDS = {"C/F", "BALANCE C/F", "BAL C/F"}

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


def _split_row(rest: str) -> tuple[str, list[Decimal]]:
    """(description, up to two trailing amounts) from the text after the date.

    A leading reference number is dropped from the description.
    """
    tokens = rest.split()
    amounts: list[Decimal] = []
    while tokens and len(amounts) < 2 and _AMOUNT.fullmatch(tokens[-1]):
        value = _money(tokens.pop())
        if value is not None:
            amounts.insert(0, value)
    if len(tokens) > 1 and _REFERENCE.fullmatch(tokens[0]):
        tokens.pop(0)
    return " ".join(tokens), amounts


def _find_account_number(header: list[str]) -> str | None:
    """Best effort: a standalone 9-16 digit number in the header, above the first row.

    The label ("ACCOUNT NO") is an image on HNB statements, so only the shape of the number
    can be used. Returns digits only; callers reduce it to last4 + fingerprint at once.
    """
    for text in header:
        match = _ACCOUNT.search(text)
        if match:
            return match.group(0)
    return None


@dataclass
class _Open:
    page_no: int
    day: int
    month: int
    year: int
    rest: str
    extra: list[str]


class HnbAdapter:
    code = CODE
    name = "Hatton National Bank"
    version = VERSION

    def identify(self, pages: list[str]) -> float:
        lines = [line.strip() for page in pages for line in page.splitlines()]
        upper = "\n".join(lines).upper()
        score = 0.0
        if "HNB IS A MEMBER" in upper or "HATTON NATIONAL BANK" in upper:
            score += 0.5
        if any(_ROW.match(line) and " B/F " in line.upper() + " " for line in lines):
            score += 0.3
        if any(_CLOSING.match(line) for line in lines):
            score += 0.2
        return min(score, 1.0)

    def parse(self, pages: list[str]) -> ParsedStatement:
        closing_match = None
        for page in pages:
            for raw in page.splitlines():
                match = _CLOSING.match(raw.strip())
                if match:
                    closing_match = match
        if closing_match is None:
            raise ParseError("statement_date_not_found")
        try:
            statement_date = date(
                int(closing_match.group(3)), int(closing_match.group(2)), int(closing_match.group(1))
            )
        except ValueError:
            raise ParseError("statement_date_invalid") from None

        header: list[str] = []
        for raw in pages[0].splitlines() if pages else []:
            text = raw.strip()
            if _ROW.match(text):
                break
            if text:
                header.append(text)

        statement = ParsedStatement(
            bank_code=CODE,
            adapter=CODE,
            adapter_version=VERSION,
            statement_date=statement_date,
            period_start=None,
            opening_balance=None,
            closing_balance=_money(closing_match.group(4)),
            account_number=_find_account_number(header),
        )
        builder = _Builder(statement)

        for page_no, page in enumerate(pages, start=1):
            current: _Open | None = None
            for raw in page.splitlines():
                text = raw.strip()
                if not text:
                    continue

                row = _ROW.match(text)
                if row:
                    builder.flush(current)
                    day, month, year = (int(row.group(i)) for i in (1, 2, 3))
                    current = _Open(page_no, day, month, 2000 + year, row.group(4), [])
                    continue

                if _CLOSING.match(text):
                    builder.flush(current)
                    current = None
                    continue

                totals = _TOTALS.match(text)
                if totals and builder.seen_row:
                    builder.flush(current)
                    current = None
                    builder.declare(totals.group(1), totals.group(2))
                    continue

                if _NUMBERS_ONLY.match(text) or text.upper().startswith(_STOP_PREFIXES):
                    builder.flush(current)  # page number, stray figures, footer
                    current = None
                    continue

                if current is not None:
                    current.extra.append(text)  # wrapped description
            builder.flush(current)

        builder.finish()
        return statement


class _Builder:
    def __init__(self, statement: ParsedStatement) -> None:
        self.statement = statement
        self.previous_balance: Decimal | None = None
        self.seen_b_f = False
        self.seen_row = False
        self.seq = 0

    def declare(self, debits: str, credits: str) -> None:
        withdrawals, deposits = _money(debits), _money(credits)
        self.statement.declared_withdrawals = DeclaredTotals(count=None, total=withdrawals)
        self.statement.declared_deposits = DeclaredTotals(count=None, total=deposits)

    def flush(self, row: _Open | None) -> None:
        if row is None:
            return
        statement = self.statement
        self.seen_row = True

        description, amounts = _split_row(row.rest)
        description = " ".join([description, *row.extra]).strip()
        upper = description.upper()

        try:
            row_date = date(row.year, row.month, row.day)
        except ValueError:
            statement.issues.append(Issue("invalid_date", row.page_no))
            return

        if upper in _OPENING_WORDS:
            if not self.seen_b_f:
                self.seen_b_f = True
                if not amounts:
                    statement.issues.append(Issue("opening_balance_unidentified", row.page_no))
                else:
                    statement.opening_balance = amounts[-1]
                    statement.period_start = row_date
                    self.previous_balance = amounts[-1]
            elif amounts and amounts[-1] != self.previous_balance:
                # A later page's carry-forward must continue where the last row ended.
                statement.issues.append(Issue("carry_forward_mismatch", row.page_no))
            return

        if upper in _CARRY_WORDS:
            return  # page carry-forward, not a transaction

        if not description:
            return

        if len(amounts) != 2:
            statement.issues.append(Issue("unexpected_amount_columns", row.page_no))
            return

        amount, balance = amounts
        if amount < 0:
            statement.issues.append(Issue("negative_amount", row.page_no))
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
        if not self.seen_b_f:
            self.statement.issues.append(Issue("opening_balance_unidentified"))
