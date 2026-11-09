"""Why a transaction is flagged, and a plain-language explanation of it (docs/08, 4.5).

CODE decides what is unusual, and writes each reason in a fixed sentence. The local model is only
asked to rephrase those reasons for a non-expert and to say what to check. It is given the
reasons, the money direction and the category name, and nothing else: no description (untrusted
PDF text), no amount, no date, no account. Its answer passes the same number guard as the month
summary and is dropped if it invents a figure.

Reasons (`code`):
* from the statement check: row_balance_mismatch, row_amounts_invalid, suspicious_date_gap,
  date_outside_period, statement_not_reconciled, and a generic row_flagged;
* from your own history (only reconciled or accepted statements, repeated rows left out):
  large_for_category (at least 3x the usual and in your top 10% for that category, needing 5
  comparable payments), first_time_large (a payee seen once, among your largest payments,
  needing 30 payments), possible_double_charge (same description and amount within a day),
  negative_balance.
"""

import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from statistics import median

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Category, Document, Transaction
from app.services import llm_guard, llm_json
from app.services.categorizer import description_stem
from app.services.extraction import ACTIVE_STATUSES
from app.services.llm_classifier import LlmUnavailable

MIN_PEERS = 5
LARGE_TIMES = 3
MIN_PAYMENTS_FOR_NEW_PAYEE = 30
NEW_PAYEE_TIMES = 2
MAX_EXPLANATION = 400

TITLES = {
    "row_balance_mismatch": "The balance printed after this row does not equal the previous balance plus or minus the amount, so the row may have been read wrongly.",
    "row_amounts_invalid": "The reader could not tell whether this row is a debit or a credit.",
    "suspicious_date_gap": "The date is almost a year away from the row before it, so it may be mis-dated.",
    "date_outside_period": "The date falls outside the period the statement covers.",
    "unexpected_amount_columns": "The row has a different number of amount columns than expected.",
    "negative_amount": "The row has a negative amount, which the reader does not expect.",
    "invalid_date": "The reader could not make sense of this row's date.",
    "statement_not_reconciled": "Its statement did not reconcile, so it is left out of your totals until you review it.",
    "row_flagged": "The statement reader was not sure about this row.",
    "possible_double_charge": "Another transaction with the same description and amount is within a day of this one, which may be a double charge.",
    "negative_balance": "The account balance after this row is below zero.",
    "first_time_large": "This payee appears for the first time, and the amount is among your largest payments.",
}


@dataclass
class Flag:
    code: str
    title: str  # a fixed sentence; never contains an amount or the description


def _counted(user_id: int):
    return (
        Transaction.user_id == user_id,
        Transaction.is_duplicate.is_(False),
        Transaction.document_id.in_(
            select(Document.id).where(Document.user_id == user_id, Document.status.in_(ACTIVE_STATUSES))
        ),
    )


def _p90(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]


def flags_for(db: Session, user_id: int, t: Transaction) -> list[Flag]:
    out: list[Flag] = []
    document = db.get(Document, t.document_id)

    # 1. what the statement check said about this row
    seen: set[str] = set()
    for issue in ((document.validation or {}).get("issues") or []) if document else []:
        code = issue.get("code")
        if issue.get("seq") == t.seq and code and code not in seen:
            seen.add(code)
            out.append(Flag(code, TITLES.get(code, TITLES["row_flagged"])))
    if t.validation_status != "ok" and not seen:
        code = "row_balance_mismatch" if t.validation_status == "balance_mismatch" else "row_flagged"
        out.append(Flag(code, TITLES[code]))
    if document is not None and document.status == "needs_review":
        out.append(Flag("statement_not_reconciled", TITLES["statement_not_reconciled"]))

    # 2. what your own history says
    amount = t.debit if t.debit > 0 else t.credit
    stem = description_stem(t.original_description)

    if t.debit > 0 and t.category_id is not None:
        category = db.get(Category, t.category_id)
        if category is not None and category.kind != "transfer":
            peers = [
                d
                for (d,) in db.execute(
                    select(Transaction.debit).where(
                        *_counted(user_id),
                        Transaction.category_id == t.category_id,
                        Transaction.debit > 0,
                        Transaction.id != t.id,
                    )
                )
            ]
            if len(peers) >= MIN_PEERS:
                usual = Decimal(str(median(peers)))
                if usual > 0 and t.debit >= usual * LARGE_TIMES and t.debit >= _p90(peers):
                    times = int((t.debit / usual).to_integral_value())
                    out.append(
                        Flag(
                            "large_for_category",
                            f"The amount is about {times} times the usual for {category.name}.",
                        )
                    )

    if t.debit > 0 and stem:
        debits = [d for (d,) in db.execute(select(Transaction.debit).where(*_counted(user_id), Transaction.debit > 0))]
        if len(debits) >= MIN_PAYMENTS_FOR_NEW_PAYEE and t.debit >= Decimal(str(median(debits))) * NEW_PAYEE_TIMES and t.debit >= _p90(debits):
            same = sum(
                count
                for description, count in db.execute(
                    select(Transaction.original_description, func.count())
                    .where(*_counted(user_id))
                    .group_by(Transaction.original_description)
                )
                if description_stem(description) == stem
            )
            if same <= 1:
                out.append(Flag("first_time_large", TITLES["first_time_large"]))

    if amount > 0 and stem:
        nearby = db.execute(
            select(Transaction.original_description)
            .where(
                *_counted(user_id),
                Transaction.id != t.id,
                Transaction.transaction_date >= t.transaction_date - timedelta(days=1),
                Transaction.transaction_date <= t.transaction_date + timedelta(days=1),
                Transaction.debit == t.debit,
                Transaction.credit == t.credit,
            )
        ).all()
        if any(description_stem(d) == stem for (d,) in nearby):
            out.append(Flag("possible_double_charge", TITLES["possible_double_charge"]))

    if t.running_balance < 0:
        out.append(Flag("negative_balance", TITLES["negative_balance"]))
    return out


# --- the explanation -----------------------------------------------------------------------------------


class Explanation(BaseModel):
    explanation: str = Field(max_length=1000)
    check: str = Field(max_length=500)


SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}, "check": {"type": "string"}},
    "required": ["explanation", "check"],
}


def facts_text(t: Transaction, flags: list[Flag], category_name: str | None) -> str:
    lines = [f"- {f.title}" for f in flags]
    lines.append(f"Money direction: {'out' if t.debit > 0 else 'in'}")
    lines.append(f"Category: {category_name or 'none yet'}")
    return "\n".join(lines)


def prompt(facts: str) -> str:
    return (
        "A personal finance app flagged one bank transaction. The reasons were found by the app, not by you.\n"
        "Explain them to the account owner in plain English. `explanation`: one or two sentences on what "
        "looks unusual and why it might matter. `check`: one short sentence on what to check. Use only the "
        "reasons below. Do not guess the shop or payee, and do not add any number that is not listed. "
        "Never mention amounts of money. Answer with JSON only.\n\n"
        f"Reasons:\n{facts}\n"
    )


def explain(
    db: Session,
    settings: Settings,
    t: Transaction,
    flags: list[Flag],
    category_name: str | None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[Explanation | None, int | None, str | None]:
    """(explanation or None, model milliseconds, a note when it was not used or was rejected)."""
    if not settings.llm_classify_enabled:
        return None, None, None
    facts = facts_text(t, flags, category_name)
    began = time.perf_counter()
    try:
        with llm_json.open_client(settings, transport) as client:
            digest = llm_json.digest_or_raise(client, settings)
            reply = llm_json.ask(db, settings, client, digest, "explain", prompt(facts), SCHEMA, Explanation)
    except LlmUnavailable:
        return None, None, "The local AI is not available. The reasons above come from the app's own checks."
    took = round((time.perf_counter() - began) * 1000)
    if reply is None:
        return None, took, "The local AI did not give a usable answer."
    what = llm_guard.clean(reply.explanation, facts, MAX_EXPLANATION)
    check = llm_guard.clean(reply.check, facts, MAX_EXPLANATION)
    if what is None or check is None:
        return None, took, "The local AI's explanation used a figure it was not given, so it was left out."
    return Explanation(explanation=what, check=check), took, None
