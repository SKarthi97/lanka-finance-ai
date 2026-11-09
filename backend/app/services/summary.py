"""A plain-language summary of one month (docs/08, 4.4).

Two layers:
1. Code computes the facts and writes a bullet summary WITH the real amounts. Always shown.
2. The local model may add a short friendly paragraph. It is given the facts WITHOUT any amounts
   (only percentages, counts and names), and what it writes is checked (`llm_guard`): any number
   not in the facts, or any mention of money, makes the paragraph be dropped. So it can phrase
   but cannot invent or reveal a figure.
"""

import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Category, Document
from app.routers.overview import _totals
from app.services import budgets, llm_guard, llm_json, recurring
from app.services.extraction import ACTIVE_STATUSES
from app.services.llm_classifier import LlmUnavailable

ZERO = Decimal("0.00")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
MAX_NARRATIVE = 700
MIN_RISE_SHARE = Decimal("0.10")  # a category must rise by 10% of the month's spending to be named


@dataclass
class Facts:
    label: str
    prev_label: str
    transactions: int = 0
    income: Decimal = ZERO
    expense: Decimal = ZERO
    net: Decimal = ZERO
    transfers: bool = False
    compared: bool = False  # both months have transactions, so changes mean something
    income_change: int | None = None  # whole percent against the previous month
    expense_change: int | None = None
    saving_rate: int | None = None
    top: list[tuple[str, Decimal, int]] = field(default_factory=list)  # name, spent, share %
    riser: tuple[str, int | None] | None = None  # category that rose most; % or None if new
    over: list[str] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    overdue: int = 0
    uncategorised: int = 0


def _label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def _percent(current: Decimal, previous: Decimal) -> int | None:
    if previous <= 0:
        return None
    return int(((current - previous) / previous * 100).to_integral_value())


def compute_facts(db: Session, user_id: int, year: int, month: int, today: date | None = None) -> Facts:
    start, end = budgets.month_bounds(year, month)
    prev_start = date(year - (month == 1), (month - 2) % 12 + 1, 1)
    facts = Facts(label=_label(year, month), prev_label=_label(prev_start.year, prev_start.month))

    included = select(Document.id).where(
        Document.user_id == user_id, Document.status.in_(ACTIVE_STATUSES)
    )
    categories = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user_id))}
    now, now_by_cat = _totals(db, included, start, end, categories)
    before, before_by_cat = _totals(db, included, prev_start, start, categories)

    facts.transactions = now.transactions
    facts.income, facts.expense, facts.net = now.income, now.expense, now.net
    facts.transfers = (now.transfers_in + now.transfers_out) > 0
    facts.uncategorised = now.uncategorised
    if now.transactions == 0:
        return facts

    facts.compared = before.transactions > 0
    if facts.compared:
        facts.income_change = _percent(now.income, before.income)
        facts.expense_change = _percent(now.expense, before.expense)
    if now.income > 0 and now.net >= 0:
        facts.saving_rate = int((now.net / now.income * 100).to_integral_value())

    spending = [c for c in now_by_cat if c.kind != "transfer" and c.expense > 0]
    spending.sort(key=lambda c: (-c.expense, c.name))
    total = sum((c.expense for c in spending), ZERO)
    for c in spending[:3]:
        share = int((c.expense / total * 100).to_integral_value()) if total > 0 else 0
        facts.top.append((c.name, c.expense, share))

    if facts.compared:
        last = {c.category_id: c.expense for c in before_by_cat}
        best: tuple[Decimal, str, int | None] | None = None
        for c in spending:
            if c.category_id is None:
                continue
            was = last.get(c.category_id, ZERO)
            rise = c.expense - was
            if rise >= now.expense * MIN_RISE_SHARE and (best is None or rise > best[0]):
                best = (rise, c.name, _percent(c.expense, was))
        if best:
            facts.riser = (best[1], best[2])

    for line in budgets.lines(db, user_id, year, month):
        (facts.over if line.state == "over" else facts.near if line.state == "near" else []).append(
            line.category_name
        )
    facts.overdue = sum(
        1
        for r in recurring.find(db, user_id, today=today)
        if r.state == "overdue" and r.direction == "expense"
    )
    return facts


def _lkr(value: Decimal) -> str:
    return f"LKR {value:,.2f}"


def _names(items: list[str]) -> str:
    return ", ".join(items[:-1]) + f" and {items[-1]}" if len(items) > 1 else items[0]


def bullets(f: Facts) -> list[str]:
    """The summary in sentences, written by code, with the real amounts."""
    if f.transactions == 0:
        return [f"No transactions in {f.label}."]
    out = [
        f"Income {_lkr(f.income)}, spending {_lkr(f.expense)}, "
        + (f"net {_lkr(f.net)} saved." if f.net >= 0 else f"net {_lkr(-f.net)} overspent.")
    ]
    if f.expense_change is not None:
        word = "up" if f.expense_change > 0 else "down" if f.expense_change < 0 else "unchanged"
        out.append(
            f"Spending is {word}{f' {abs(f.expense_change)}%' if f.expense_change else ''} on {f.prev_label}."
        )
    if f.income_change is not None and f.income_change != 0:
        out.append(
            f"Income is {'up' if f.income_change > 0 else 'down'} {abs(f.income_change)}% on {f.prev_label}."
        )
    if f.saving_rate is not None:
        out.append(f"You kept {f.saving_rate}% of your income.")
    if f.top:
        out.append("Biggest spending: " + ", ".join(f"{n} ({_lkr(a)}, {s}%)" for n, a, s in f.top) + ".")
    if f.riser:
        name, pct = f.riser
        out.append(f"{name} rose the most" + (f" ({pct}% more)." if pct is not None else " (new this month)."))
    if f.over:
        out.append(f"Over budget: {_names(f.over)}.")
    elif f.near:
        out.append(f"Close to the budget limit: {_names(f.near)}.")
    if f.overdue:
        out.append(f"{f.overdue} recurring payment{'s look' if f.overdue != 1 else ' looks'} overdue.")
    if f.uncategorised:
        out.append(
            f"{f.uncategorised} transaction{'s are' if f.uncategorised != 1 else ' is'} uncategorised, "
            "so category figures are partial."
        )
    if f.transfers:
        out.append("Transfers between your own accounts are not counted.")
    return out


def facts_text(f: Facts) -> str:
    """The facts for the model: percentages, counts and names only. NEVER an amount."""
    lines = [f"Month: {f.label}"]
    if f.expense_change is not None:
        lines.append(
            f"Spending compared with {f.prev_label}: "
            + ("unchanged" if f.expense_change == 0 else f"{'up' if f.expense_change > 0 else 'down'} {abs(f.expense_change)}%")
        )
    if f.income_change is not None:
        lines.append(
            f"Income compared with {f.prev_label}: "
            + ("unchanged" if f.income_change == 0 else f"{'up' if f.income_change > 0 else 'down'} {abs(f.income_change)}%")
        )
    lines.append(
        f"Kept {f.saving_rate}% of income" if f.saving_rate is not None else "Spent more than was earned or had no income"
    )
    if f.top:
        lines.append("Largest spending categories: " + "; ".join(f"{n} {s}% of spending" for n, _, s in f.top))
    if f.riser:
        name, pct = f.riser
        lines.append(f"Biggest rise: {name}" + (f", {pct}% more than last month" if pct is not None else ", new this month"))
    if f.over:
        lines.append("Over budget: " + ", ".join(f.over))
    if f.overdue:
        lines.append(f"Recurring payments that look overdue: {f.overdue}")
    if f.uncategorised:
        lines.append(f"Uncategorised transactions: {f.uncategorised}")
    return "\n".join(lines)


class Narrative(BaseModel):
    summary: str = Field(max_length=2000)


SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def prompt(facts: str) -> str:
    return (
        "You write a short, friendly summary of one person's month of spending for a personal finance app.\n"
        "Use ONLY the facts below. Do not add any number, date or fact that is not listed, and never "
        "mention amounts of money or currencies. Write 2 to 4 plain sentences. Say nothing about a "
        "topic that has no fact. Answer with JSON only.\n\n"
        f"Facts:\n{facts}\n"
    )


def narrate(
    db: Session,
    settings: Settings,
    f: Facts,
    transport: httpx.BaseTransport | None = None,
) -> tuple[str | None, int | None, str | None]:
    """(paragraph or None, model milliseconds, a note when the model was not used or rejected)."""
    if not settings.llm_classify_enabled:
        return None, None, None
    text = facts_text(f)
    began = time.perf_counter()
    try:
        with llm_json.open_client(settings, transport) as client:
            digest = llm_json.digest_or_raise(client, settings)
            reply = llm_json.ask(db, settings, client, digest, "summary", prompt(text), SCHEMA, Narrative)
    except LlmUnavailable:
        return None, None, "The local AI is not available, so only the plain summary is shown."
    took = round((time.perf_counter() - began) * 1000)
    if reply is None:
        return None, took, "The local AI did not give a usable answer."
    paragraph = llm_guard.clean(reply.summary, text, MAX_NARRATIVE)
    if paragraph is None:
        return None, took, "The local AI's paragraph used a figure it was not given, so it was left out."
    return paragraph, took, None
