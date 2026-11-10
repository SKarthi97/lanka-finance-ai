"""Statements that did not come from a PDF: a CSV file, or rows typed by hand.

The rows become an ordinary document (adapter "import") and go through the same checks as a
PDF: each row must move the balance by exactly its amount, and the statement must add up from
opening to closing balance. Anything that does not goes to review. Errors are short codes,
never row text. Dates are read day first.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import ParsedStatement, ParsedTransaction
from app.adapters.generic import parse_date, parse_money
from app.config import Settings
from app.models import AuditLog, Bank, Document, Transaction
from app.services.extraction import _persist
from app.services.validation import validate

ZERO = Decimal("0.00")
MAX_ROWS = 5000

DATE_NAMES = {"date", "txn date", "transaction date", "value date", "posting date", "posted date"}
DESC_NAMES = {"description", "details", "narration", "particulars", "transaction details", "remarks", "reference", "memo"}
DEBIT_NAMES = {"debit", "debits", "withdrawal", "withdrawals", "dr", "paid out", "money out", "debit amount"}
CREDIT_NAMES = {"credit", "credits", "deposit", "deposits", "cr", "paid in", "money in", "credit amount"}
AMOUNT_NAMES = {"amount", "transaction amount", "value"}
BALANCE_NAMES = {"balance", "running balance", "closing balance", "available balance"}


class ImportError_(Exception):
    """A problem with the file or rows. `code` is short and free of row text."""

    def __init__(self, code: str, row: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.row = row


@dataclass
class Row:
    date: date
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal | None


def _find(headers: list[str], names: set[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in names:
            return index
    return None


def parse_csv(data: bytes) -> list[Row]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    table = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]

    header_at = None
    for index, record in enumerate(table[:15]):
        cells = [re.sub(r"\s+", " ", c.strip().lower()) for c in record]
        if _find(cells, DATE_NAMES) is not None and (
            _find(cells, DEBIT_NAMES | CREDIT_NAMES | AMOUNT_NAMES) is not None
        ):
            header_at = index
            headers = cells
            break
    if header_at is None:
        raise ImportError_("csv_no_header")

    i_date = _find(headers, DATE_NAMES)
    i_desc = _find(headers, DESC_NAMES)
    i_debit = _find(headers, DEBIT_NAMES)
    i_credit = _find(headers, CREDIT_NAMES)
    i_amount = _find(headers, AMOUNT_NAMES)
    i_balance = _find(headers, BALANCE_NAMES)
    if i_desc is None:
        raise ImportError_("csv_no_description")
    if i_debit is None and i_credit is None and i_amount is None:
        raise ImportError_("csv_no_amount")

    def cell(record: list[str], index: int | None) -> str:
        return record[index].strip() if index is not None and index < len(record) else ""

    rows: list[Row] = []
    for number, record in enumerate(table[header_at + 1 :], start=header_at + 2):
        when = parse_date(cell(record, i_date))
        if when is None:
            raise ImportError_("csv_bad_date", number)
        debit = credit = ZERO
        if i_debit is not None or i_credit is not None:
            for column, which in ((i_debit, "debit"), (i_credit, "credit")):
                raw = cell(record, column)
                if raw in ("", "-"):
                    continue
                value = parse_money(raw if "." in raw else raw + ".00")
                if value is None:
                    raise ImportError_("csv_bad_amount", number)
                if which == "debit":
                    debit = abs(value)
                else:
                    credit = abs(value)
        else:
            raw = cell(record, i_amount)
            value = parse_money(raw if "." in raw else raw + ".00")
            if value is None:
                raise ImportError_("csv_bad_amount", number)
            if value < 0:
                debit = -value
            else:
                credit = value
        balance = None
        raw_balance = cell(record, i_balance)
        if raw_balance:
            balance = parse_money(raw_balance if "." in raw_balance else raw_balance + ".00")
            if balance is None:
                raise ImportError_("csv_bad_balance", number)
        rows.append(Row(when, cell(record, i_desc)[:300] or "(no description)", debit, credit, balance))
    return rows


def import_rows(
    db: Session,
    settings: Settings,
    user_id: int,
    rows: list[Row],
    *,
    label: str,
    source: str,
    bank_code: str | None = None,
    account_number: str | None = None,
    opening_balance: Decimal | None = None,
    closing_balance: Decimal | None = None,
) -> Document:
    """Store rows as a document. Raises ImportError_ for unusable input, ValueError("duplicate")."""
    if not rows:
        raise ImportError_("no_rows")
    if len(rows) > MAX_ROWS:
        raise ImportError_("too_many_rows")
    for number, row in enumerate(rows, start=1):
        if (row.debit > ZERO) == (row.credit > ZERO):
            raise ImportError_("row_amounts_invalid", number)

    ordered = sorted(enumerate(rows), key=lambda pair: (pair[1].date, pair[0]))  # stable by date
    rows = [r for _, r in ordered]

    have_balances = all(r.balance is not None for r in rows)
    if opening_balance is None:
        if have_balances:
            first = rows[0]
            opening_balance = first.balance - first.credit + first.debit  # type: ignore[operator]
        else:
            raise ImportError_("opening_balance_needed")

    transactions: list[ParsedTransaction] = []
    running = opening_balance
    for seq, row in enumerate(rows, start=1):
        running = running - row.debit + row.credit
        balance = row.balance if row.balance is not None else running
        transactions.append(ParsedTransaction(seq, 1, row.date, row.description, row.debit, row.credit, balance))
        running = balance  # trust a printed balance, so a mismatch shows up on the next row

    final = closing_balance if closing_balance is not None else transactions[-1].balance
    parsed = ParsedStatement(
        bank_code="",
        adapter="import",
        adapter_version="1",
        statement_date=transactions[-1].date,
        period_start=transactions[0].date,
        opening_balance=opening_balance,
        closing_balance=final,
        account_number=account_number or None,
        transactions=transactions,
    )

    digest = hashlib.sha256(
        json.dumps(
            [source, bank_code or "", [(r.date.isoformat(), r.description, str(r.debit), str(r.credit), str(r.balance)) for r in rows]]
        ).encode()
    ).hexdigest()
    if db.scalar(select(Document.id).where(Document.user_id == user_id, Document.sha256 == digest)):
        raise ValueError("duplicate")

    bank = db.scalar(select(Bank).where(Bank.code == bank_code)) if bank_code else None
    if bank_code and bank is None:
        raise ImportError_("unknown_bank")

    document = Document(
        user_id=user_id,
        bank_id=bank.id if bank else None,
        sha256=digest,
        storage_path="",
        original_filename=label[:255] or "import",
        size_bytes=0,
        page_count=None,
        is_encrypted=False,
        status="processing",
        file_deleted_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    result = validate(parsed)
    _persist(db, document, parsed, result, settings)
    for tx in db.scalars(select(Transaction).where(Transaction.document_id == document.id)):
        tx.extraction_method = "import"
    db.add(
        AuditLog(
            user_id=user_id,
            action=f"document.{source}",
            entity="document",
            entity_id=str(document.id),
            detail={"rows": len(rows)},
        )
    )
    db.commit()
    return document
