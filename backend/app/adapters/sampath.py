"""Sampath Bank adapter, account statements ("Statement of Account").

Layout it is written for (text as PyMuPDF extracts it, one table row per line; the logo, the
title and the column headings are images, so they are not in the text layer):

    999999999999 LKR PAGE_NO: 1                      header: account number, currency, page
    FOR THE PERIOD : 22-12-2025 to 31-12-2025 DATE: 01-01-2026
    22DEC2025 0.00                                   opening balance (4-digit year, no label)
    22Dec25 JAFFNA CDK 213758 5,000.00 5,000.00Cr    date, branch code, particulars, ONE
                                                     amount, balance with a Cr/Dr suffix
    31Dec2025 C/F 4,000.00Cr                         closing balance carried forward
    ---------------------------------------------
    TOTAL : 1,000.00 5,000.00                        debits, credits (no item counts)

Dates carry a two-digit year on transaction rows, four on the opening and closing rows. A
row holds one amount, so debit vs credit is decided from the running-balance movement and
then checked by the validation layer, as for BOC and HNB. Cr/Dr makes the balance
positive/negative; a bare balance (a zero opening) is positive. The statement date is the end
of the period, not the DATE printed on the right, which is the day it was produced.

Text without a date is ignored: particulars are cut to the column width, not wrapped, and
this keeps header text on later pages from being glued onto the previous row.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.adapters.base import (
    DeclaredTotals,
    Issue,
    ParsedStatement,
    ParsedTransaction,
    ParseError,
)

CODE = "sampath"
VERSION = "1"

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_AMOUNT_TEXT = r"(?:\d[\d,]*)?\.\d{2}"
_AMOUNT = re.compile(rf"^{_AMOUNT_TEXT}$")
_BALANCE = re.compile(rf"^({_AMOUNT_TEXT})(CR|DR)?$", re.IGNORECASE)
_SUFFIX = re.compile(r"^(CR|DR)$", re.IGNORECASE)
_ROW = re.compile(r"^(\d{2})([A-Za-z]{3})(\d{4}|\d{2})(?:\s+(.*))?$")
_PERIOD = re.compile(
    r"PERIOD\s*:\s*(\d{2})-(\d{2})-(\d{4})\s+TO\s+(\d{2})-(\d{2})-(\d{4})", re.IGNORECASE
)
_TOTALS = re.compile(rf"^TOTAL\s*:\s*({_AMOUNT_TEXT})\s+({_AMOUNT_TEXT})$", re.IGNORECASE)
_PAGE_NO = re.compile(r"PAGE_NO\s*:\s*\d+", re.IGNORECASE)
_ACCOUNT = re.compile(r"(?<![\d,.])\d{9,16}(?![\d,.])")
_OPENING_WORDS = {"B/F", "BF"}
_CLOSING_WORDS = {"C/F", "CF"}

_CENTS = Decimal("0.01")


def _money(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _lines(page: str) -> list[str]:
    return [line.strip() for line in page.splitlines() if line.strip()]


def _row_date(match: re.Match) -> date | None:
    month = _MONTHS.get(match.group(2).upper())
    if month is None:
        return None
    year = int(match.group(3))
    try:
        return date(year if len(match.group(3)) == 4 else 2000 + year, month, int(match.group(1)))
    except ValueError:
        return None


def _is_row(text: str) -> bool:
    match = _ROW.match(text)
    return match is not None and match.group(2).upper() in _MONTHS


def _period(pages: list[str]) -> tuple[date, date] | None:
    for page in pages:
        for text in _lines(page):
            match = _PERIOD.search(text)
            if match:
                try:
                    start = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                    end = date(int(match.group(6)), int(match.group(5)), int(match.group(4)))
                except ValueError:
                    return None
                return start, end
    return None


def _find_account_number(pages: list[str]) -> str | None:
    """A standalone 9-16 digit number in the first page's header, above the first row.

    The label is an image, so only the shape of the number can be used. Returns digits only;
    callers reduce it to last4 + fingerprint at once.
    """
    for text in _lines(pages[0]) if pages else []:
        if _is_row(text):
            break
        found = _ACCOUNT.search(text)
        if found:
            return found.group(0)
    return None


def _split(rest: str) -> tuple[list[str], Decimal | None, Decimal | None]:
    """(particulars tokens, amount, signed balance) from the text after the date."""
    tokens = rest.split()
    suffix = None
    if len(tokens) > 1 and _SUFFIX.match(tokens[-1]) and _AMOUNT.match(tokens[-2]):
        suffix = tokens.pop().upper()  # "5,000.00 Cr" written with a space

    balance: Decimal | None = None
    if tokens:
        matched = _BALANCE.match(tokens[-1])
        if matched:
            tokens.pop()
            balance = _money(matched.group(1))
            suffix = (matched.group(2) or suffix or "").upper()
            if balance is not None and suffix == "DR":
                balance = -balance

    amount: Decimal | None = None
    if balance is not None and tokens and _AMOUNT.match(tokens[-1]):
        amount = _money(tokens.pop())
    return tokens, amount, balance


class SampathAdapter:
    code = CODE
    name = "Sampath Bank"
    version = VERSION

    def identify(self, pages: list[str]) -> float:
        lines = [line for page in pages for line in _lines(page)]
        text = "\n".join(lines).upper()
        score = 0.0
        if any(_PERIOD.search(line) for line in lines):
            score += 0.4
        if any(_PAGE_NO.search(line) for line in lines):
            score += 0.2
        if any(_is_row(line) and _BALANCE.match(line.split()[-1]) for line in lines):
            score += 0.2
        if any(_TOTALS.match(line) for line in lines):
            score += 0.1
        if "SAMPATH" in text:
            score += 0.5
        return min(score, 1.0)

    def parse(self, pages: list[str]) -> ParsedStatement:
        period = _period(pages)
        if period is None:
            raise ParseError("statement_date_not_found")
        start, end = period

        statement = ParsedStatement(
            bank_code=CODE,
            adapter=CODE,
            adapter_version=VERSION,
            statement_date=end,
            period_start=start,
            opening_balance=None,
            closing_balance=None,
            account_number=_find_account_number(pages),
        )

        previous: Decimal | None = None
        seen_opening = False
        seen_closing = False
        seq = 0

        for page_no, page in enumerate(pages, start=1):
            for text in _lines(page):
                totals = _TOTALS.match(text)
                if totals:
                    statement.declared_withdrawals = DeclaredTotals(count=None, total=_money(totals.group(1)))
                    statement.declared_deposits = DeclaredTotals(count=None, total=_money(totals.group(2)))
                    continue
                if not _is_row(text):
                    continue

                row = _ROW.match(text)
                row_date = _row_date(row)
                if row_date is None:
                    statement.issues.append(Issue("invalid_date", page_no))
                    continue
                tokens, amount, balance = _split(row.group(4) or "")
                label = " ".join(tokens).upper()

                # Opening balance (first unlabelled/B-F row) and carry-forward rows.
                if amount is None and (not tokens or label in _OPENING_WORDS):
                    if not seen_opening:
                        seen_opening = True
                        if balance is None:
                            statement.issues.append(Issue("opening_balance_unidentified", page_no))
                        else:
                            statement.opening_balance = balance
                            previous = balance
                    elif balance is not None and balance != previous:
                        statement.issues.append(Issue("carry_forward_mismatch", page_no))
                    continue
                if amount is None and label in _CLOSING_WORDS:
                    seen_closing = True
                    if balance is None:
                        statement.issues.append(Issue("closing_balance_unidentified", page_no))
                    else:
                        statement.closing_balance = balance
                    continue

                if amount is None or balance is None or len(tokens) < 1:
                    statement.issues.append(Issue("unexpected_amount_columns", page_no))
                    continue

                # The first token is the branch code (JAFFNA, H/O, NSC); keep it only when
                # it is all there is.
                description = " ".join(tokens[1:] if len(tokens) > 1 else tokens)

                debit = credit = Decimal("0.00")
                issue_code: str | None = None
                if previous is None:
                    issue_code = "opening_balance_unavailable"
                else:
                    movement = balance - previous
                    if movement > 0:
                        credit = amount
                    elif movement < 0:
                        debit = amount
                    else:
                        issue_code = "no_balance_movement"
                    if abs(abs(movement) - amount) > Decimal("0.02"):
                        issue_code = "balance_mismatch"

                seq += 1
                statement.transactions.append(
                    ParsedTransaction(
                        seq=seq,
                        page_no=page_no,
                        date=row_date,
                        description=description,
                        debit=debit.quantize(_CENTS),
                        credit=credit.quantize(_CENTS),
                        balance=balance.quantize(_CENTS),
                    )
                )
                if issue_code:
                    statement.issues.append(Issue(issue_code, page_no, seq))
                previous = balance

        if not seen_opening:
            statement.issues.append(Issue("opening_balance_unidentified"))
        if not seen_closing:
            statement.issues.append(Issue("closing_balance_unidentified"))
        return statement
