"""Best-effort reader for a statement layout no bank adapter recognises.

It looks for lines of the form  DATE  DESCRIPTION  AMOUNT [AMOUNT]  BALANCE  and keeps the
result only as far as the arithmetic holds: every row must move the balance by exactly its
amount. It never marks a statement as reconciled on its own: the closing balance is read
from the statement's own "closing balance" line, and without one the statement goes to
review. The date must carry a year (no guessing). Pure text in, structured data out.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.adapters.base import Issue, ParsedStatement, ParsedTransaction, ParseError

ZERO = Decimal("0.00")
MIN_ROWS = 3

_DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[ -][A-Za-z]{3}[ -]\d{2,4})"
_MONEY = r"-?\(?\d{1,3}(?:,\d{3})*\.\d{2}\)?(?:\s?(?:CR|DR|Cr|Dr))?"
_LINE = re.compile(rf"^\s*({_DATE})\s+(.*?)\s+((?:{_MONEY}\s*){{1,3}})\s*$")
_OPENING = re.compile(r"(?:opening\s+balance|balance\s+(?:b/?f|brought\s+forward)|brought\s+forward)\D{0,20}(" + _MONEY + ")", re.I)
_CLOSING = re.compile(r"(?:closing\s+balance|balance\s+(?:c/?f|carried\s+forward)|carried\s+forward)\D{0,20}(" + _MONEY + ")", re.I)
_ACCOUNT = re.compile(r"account\s*(?:no\.?|number|#)\s*[:\-]?\s*([\d][\d\- ]{5,})", re.I)

_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%d %b %Y", "%d-%b-%Y", "%d %b %y", "%d-%b-%y")


def parse_date(text: str) -> date | None:
    """Day first (the usual order in Sri Lanka)."""
    cleaned = " ".join(text.split())
    for fmt in _FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(text: str) -> Decimal | None:
    cleaned = text.strip()
    negative = cleaned.startswith("-") or (cleaned.startswith("(") and cleaned.endswith(")"))
    digits = re.sub(r"[^\d.]", "", cleaned)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    return value.quantize(ZERO)


class GenericAdapter:
    code = "generic"
    name = "Unrecognised layout"
    version = "1"

    def identify(self, pages: list[str]) -> float:
        return 0.0  # only ever used as the fallback, never chosen by score

    def parse(self, pages: list[str]) -> ParsedStatement:
        rows: list[tuple[int, date, str, list[Decimal]]] = []
        opening = closing = None
        account = None
        for page_no, text in enumerate(pages, start=1):
            if account is None and (m := _ACCOUNT.search(text)):
                account = re.sub(r"\D", "", m.group(1))
            if opening is None and (m := _OPENING.search(text)):
                opening = parse_money(m.group(1))
            if m := _CLOSING.search(text):
                closing = parse_money(m.group(1))
            for line in text.splitlines():
                match = _LINE.match(line)
                if not match:
                    continue
                when = parse_date(match.group(1))
                if when is None:
                    continue
                amounts = [parse_money(a) for a in re.findall(_MONEY, match.group(3))]
                if any(a is None for a in amounts):
                    continue
                rows.append((page_no, when, match.group(2).strip(), amounts))  # type: ignore[arg-type]

        if len(rows) < MIN_ROWS:
            raise ParseError("unsupported_layout")

        issues: list[Issue] = []
        transactions: list[ParsedTransaction] = []
        previous = opening
        for seq, (page_no, when, description, amounts) in enumerate(rows, start=1):
            balance = amounts[-1]
            debit = credit = ZERO
            if len(amounts) == 3:
                debit, credit = abs(amounts[0]), abs(amounts[1])
            elif len(amounts) == 2:
                amount = abs(amounts[0])
                if previous is None:
                    # The first row's direction cannot be told without an opening balance.
                    raise ParseError("opening_balance_unidentified")
                if previous - amount == balance:
                    debit = amount
                elif previous + amount == balance:
                    credit = amount
                else:
                    issues.append(Issue("balance_mismatch", page_no, seq))
                    debit = amount
            else:  # a lone number: a balance line, not a transaction
                issues.append(Issue("unexpected_amount_columns", page_no, seq))
            transactions.append(ParsedTransaction(seq, page_no, when, description[:300], debit, credit, balance))
            previous = balance

        first = transactions[0]
        if opening is None and len(rows[0][3]) == 3:
            opening = first.balance + first.debit - first.credit
        return ParsedStatement(
            bank_code="",
            adapter="generic",
            adapter_version=self.version,
            statement_date=transactions[-1].date,
            period_start=transactions[0].date,
            opening_balance=opening,
            closing_balance=closing,  # only from the statement's own line: no line, no auto-reconcile
            account_number=account,
            transactions=transactions,
            issues=issues,
        )
