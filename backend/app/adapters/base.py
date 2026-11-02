"""Bank adapter interface (simplified from docs/00-architecture.md section 7).

Adapters are pure: text in, structured data out. No I/O, no database, no logging of
statement contents. Issues carry codes and positions only, never text.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


class ParseError(Exception):
    """The statement cannot be parsed. Deterministic, so retrying cannot help.

    The message is a short code, never statement text.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Issue:
    code: str
    page: int | None = None
    seq: int | None = None


@dataclass
class ParsedTransaction:
    seq: int  # 1-based order within the statement
    page_no: int  # page of the row's date line
    date: date
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass
class ParsedStatement:
    bank_code: str
    adapter: str
    adapter_version: str
    statement_date: date
    period_start: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    # SENSITIVE. Callers reduce it to last4 + fingerprint at once; never log or store it.
    account_number: str | None
    transactions: list[ParsedTransaction] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


class BankAdapter(Protocol):
    code: str
    name: str
    version: str

    def identify(self, pages: list[str]) -> float:
        """Confidence 0..1 that these pages are this bank's statement."""
        ...

    def parse(self, pages: list[str]) -> ParsedStatement:
        """Raise ParseError for layouts that cannot be parsed."""
        ...
