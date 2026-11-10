"""Figures for a Sri Lankan tax return (Inland Revenue Department), taken from the statements.

The year of assessment runs from 1 April to 31 March ("2025/26" is 1 April 2025 to 31 March 2026).
This module only sorts what the statements show into the heads a return asks about: it does not
compute tax, apply reliefs or decide what is taxable, because the rates and rules change and some
of the facts (tax deducted by an employer, a bank that credits interest already after tax) are not
on a bank statement at all. Everything is exact decimal arithmetic on the figures from the statements.
"""

import re
from datetime import date

from app.tuning import NEAR_AFTER_DAYS, NEAR_BEFORE_DAYS  # noqa: F401

PERIOD_START_MONTH = 4  # April

EMPLOYMENT = "employment"
INTEREST = "interest"
DIVIDENDS = "dividends"
OTHER_INCOME = "other_income"
DEPOSITS = "deposits"

HEAD_LABEL = {
    EMPLOYMENT: "Employment income",
    INTEREST: "Interest",
    DIVIDENDS: "Dividends",
    OTHER_INCOME: "Other income",
    DEPOSITS: "Deposits",
}

# categories that give the named heads; any other income category counts as other income
_BY_CATEGORY = {
    "Salary": EMPLOYMENT,
    "Interest income": INTEREST,
    "Dividend": DIVIDENDS,
    "Deposits": DEPOSITS,
}

# Banks word withheld tax in many ways ("AIT" is advance income tax, which replaced WHT on interest).
TAX_WORDS = ("INTEREST", "WHT", "WITHHELD", "WITHHOLDING", "ADVANCE INCOME", "W/H", "WH TAX", "INT TAX")
TAX_WORD_REGEXES = (r"\bAIT\b",)


def assessment_year(today: date) -> int:
    """The year of assessment (by its starting year) that `today` falls in."""
    return today.year if today.month >= PERIOD_START_MONTH else today.year - 1


def bounds(year: int) -> tuple[date, date]:
    return date(year, PERIOD_START_MONTH, 1), date(year + 1, PERIOD_START_MONTH - 1, 31)


def label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


def months(year: int) -> list[tuple[int, int]]:
    """April to March, as (year, month)."""
    return [(year, m) for m in range(PERIOD_START_MONTH, 13)] + [(year + 1, m) for m in range(1, PERIOD_START_MONTH)]


def head_of(category_name: str | None, kind: str | None) -> str | None:
    """Which head an income row belongs to; None for anything that is not income."""
    if kind != "income":
        return None
    return _BY_CATEGORY.get(category_name or "", OTHER_INCOME)


def tax_head(description: str) -> str:
    """What a tax line was taken from, going by its wording: interest, dividends, or something else
    (stamp duty and so on). Wording that says nothing is left as "other"; `near` can still place it."""
    text = description.upper()
    if "STAMP" in text:
        return "other"
    if "DIVIDEND" in text:
        return DIVIDENDS
    if any(word in text for word in TAX_WORDS) or any(re.search(r, text) for r in TAX_WORD_REGEXES):
        return INTEREST
    return "other"


def near(days: list[date], when: date) -> bool:
    """Is `when` just around one of `days` (the dates of an account's interest or dividend credits)?"""
    return any(-NEAR_BEFORE_DAYS <= (when - d).days <= NEAR_AFTER_DAYS for d in days)
