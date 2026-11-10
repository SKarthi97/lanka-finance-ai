"""Transaction categorisation (docs/00-architecture.md, Phase 4).

Order of authority, strongest first:
  1. manual         you set this transaction yourself; nothing overwrites it
  2. user rules     patterns you wrote or that were learned from your corrections
  3. built-in rules patterns for common bank wording
  4. llm            the local model's suggestion, only when confident (see llm_classifier)
Anything left is uncategorised and goes to the review queue.

Rules match the normalised description (upper case, single spaces). Among matching rules the
higher priority wins, then the longer pattern, so "INTEREST WITHHELD" (tax) beats "INTEREST"
(income). Nothing here logs descriptions, amounts or account numbers.
"""

import re
from decimal import Decimal
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Category,
    ClassificationFeedback,
    ClassificationRule,
    Setting,
    Transaction,
)

SYSTEM_VERSION = 3  # bump when CATEGORIES / RULES below gain entries

KINDS = ("income", "expense", "transfer")

# (name, kind). Transfers move your own money around, so they are left out of income
# and expense totals.
CATEGORIES: list[tuple[str, str]] = [
    ("Salary", "income"),
    ("Interest income", "income"),
    ("Dividend", "income"),
    ("Deposits", "income"),
    ("Other income", "income"),
    ("Transfers", "transfer"),
    ("Cash withdrawal", "expense"),
    ("Bank charges", "expense"),
    ("Tax", "expense"),
    ("Loan repayment", "expense"),
    ("Card payment", "expense"),
    ("Utilities", "expense"),
    ("Food and dining", "expense"),
    ("Shopping", "expense"),
    ("Transport", "expense"),
    ("Fuel", "expense"),
    ("Healthcare", "expense"),
    ("Education", "expense"),
    ("Insurance", "expense"),
    ("Entertainment", "expense"),
    ("Investment", "expense"),
    ("Other expense", "expense"),
]

# (pattern, type, category, priority). Generic bank wording only: nothing personal.
RULES: list[tuple[str, str, str, int]] = [
    # taxes and charges first: they contain words that would otherwise look like income
    ("INTEREST WITHHELD", "contains", "Tax", 30),
    ("STAMP DUTY", "contains", "Tax", 30),
    ("WHT", "word", "Tax", 30),
    ("AIT", "word", "Tax", 30),
    ("ADVANCE INCOME TAX", "contains", "Tax", 30),
    ("TAX ON INTEREST", "contains", "Tax", 30),
    ("INTEREST TAX", "contains", "Tax", 30),
    ("WITHHOLDING TAX", "contains", "Tax", 30),
    ("ATM SERVICE CHARGE", "contains", "Bank charges", 25),
    ("SERVICE CHARGE", "contains", "Bank charges", 20),
    ("SMS ALERT", "contains", "Bank charges", 20),
    ("CRIB CHARGE", "contains", "Bank charges", 20),
    ("ANNUAL FEE", "contains", "Bank charges", 20),
    ("MAINTENANCE FEE", "contains", "Bank charges", 20),
    ("CARD FEE", "contains", "Bank charges", 20),
    ("BANK CHARGE", "contains", "Bank charges", 20),
    # money moving between your own accounts
    ("DEP TO SAV", "contains", "Transfers", 25),
    ("BOOKED SAVINGS", "contains", "Transfers", 25),
    ("FUND TRANSFER", "contains", "Transfers", 15),
    ("ONLINE TRANSFER", "contains", "Transfers", 15),
    ("TRANSFER TO", "contains", "Transfers", 15),
    ("TRANSFER FROM", "contains", "Transfers", 15),
    ("CEFT", "word", "Transfers", 15),
    ("SLIPS OUT", "contains", "Transfers", 15),
    # cash and loans
    ("ATMCASHWDL", "contains", "Cash withdrawal", 20),
    ("ATM CASH WDL", "contains", "Cash withdrawal", 20),
    ("ATM CASH WITHDRAWAL", "contains", "Cash withdrawal", 20),
    ("CASH WITHDRAWAL", "contains", "Cash withdrawal", 20),
    ("WD ATM", "contains", "Cash withdrawal", 20),
    ("LOAN RECO", "contains", "Loan repayment", 20),
    ("LOAN REPAYMENT", "contains", "Loan repayment", 20),
    ("LOAN PAYMENT", "contains", "Loan repayment", 20),
    # income
    ("SALARY", "contains", "Salary", 20),
    ("PAYROLL", "contains", "Salary", 20),
    ("WAGES", "contains", "Salary", 20),
    ("INTEREST PAY", "contains", "Interest income", 10),
    ("INTEREST CREDIT", "contains", "Interest income", 10),
    ("INT PAID", "contains", "Interest income", 10),
    ("DIVIDEND", "contains", "Dividend", 20),
    ("DIV PAID", "contains", "Dividend", 20),
    ("SLIPS IN", "contains", "Deposits", 10),
    ("CASH DEPOSIT", "contains", "Deposits", 10),
    ("CHEQUE DEPOSIT", "contains", "Deposits", 10),
    # everyday spending
    ("POS PURCHASE", "contains", "Card payment", 10),
    ("POS PAYMENT", "contains", "Card payment", 10),
    ("DEBIT CARD PURCHASE", "contains", "Card payment", 10),
    ("CARD PAYMENT", "contains", "Card payment", 10),
    ("ELECTRICITY", "contains", "Utilities", 10),
    ("WATER BILL", "contains", "Utilities", 10),
    ("TELEPHONE", "contains", "Utilities", 10),
    ("CEB", "word", "Utilities", 10),
    ("LECO", "word", "Utilities", 10),
    ("SLT", "word", "Utilities", 10),
    ("DIALOG", "word", "Utilities", 10),
    ("MOBITEL", "word", "Utilities", 10),
    ("INSURANCE", "contains", "Insurance", 10),
    ("PETROL", "contains", "Fuel", 10),
    ("FUEL", "contains", "Fuel", 10),
    ("PHARMACY", "contains", "Healthcare", 10),
    ("HOSPITAL", "contains", "Healthcare", 10),
    ("RESTAURANT", "contains", "Food and dining", 10),
    ("SUPERMARKET", "contains", "Shopping", 10),
]

# Rows whose category came from rules (or nowhere) are re-evaluated when rules change.
# `manual` and `llm` are kept unless the caller says otherwise.
REEVALUATE = (None, "rule", "user_rule", "llm_unsure")
OVERRIDE_AI = REEVALUATE + ("llm",)

CORRECTION_PRIORITY = 50  # your corrections beat built-in rules
_CHUNK = 500


def normalise(description: str) -> str:
    return " ".join((description or "").upper().split())


def description_stem(description: str) -> str:
    """The reusable part of a description: words without digits, at most four.

    "LOAN RECO 12345678" -> "LOAN RECO", so one correction covers every month's payment.
    """
    tokens = [
        t
        for t in normalise(description).split()
        if not any(ch.isdigit() for ch in t) and t not in {"-", "/"}
    ]
    tokens = tokens[:4]
    # Branch and reference words at the end say where or which, not what: "... CITY BR."
    while len(tokens) > 1 and tokens[-1].strip(" -./") in _TRAILING_NOISE:
        tokens.pop()
    stem = " ".join(tokens).strip(" -./")
    return stem if len(stem) >= 3 else normalise(description)[:60]


_TRAILING_NOISE = {"BR", "BRANCH", "REF", "REFNO", "TXN", "ID", "NO"}


def cluster_stems(counts: dict[str, int], threshold: float = 0.9) -> dict[str, str]:
    """Map each stem to a representative so near-identical merchants are judged once.

    "ATMCASHWDLWELLAWATTE" and "ATMCASHWDLWELLAWATTA" differ by a typo; asking the model (or you)
    about both is wasted effort. The most frequent spelling represents the group. Short stems
    are never merged: a one-letter difference between short words is a different word.
    """
    from difflib import SequenceMatcher

    representative: dict[str, str] = {}
    reps: list[str] = []
    for stem in sorted(counts, key=lambda s: (-counts[s], s)):
        match = None
        if len(stem) >= 10:
            for rep in reps:
                if (
                    len(rep) >= 10
                    and abs(len(rep) - len(stem)) <= 3
                    and SequenceMatcher(None, rep, stem).ratio() >= threshold
                ):
                    match = rep
                    break
        if match is None:
            reps.append(stem)
            match = stem
        representative[stem] = match
    return representative


@dataclass(frozen=True)
class Rule:
    id: int
    pattern: str
    pattern_type: str
    category_id: int
    origin: str
    priority: int
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    direction: str | None = None  # "in" (a credit) or "out" (a debit)

    @property
    def conditions(self) -> int:
        return sum(x is not None for x in (self.min_amount, self.max_amount, self.direction))


@lru_cache(maxsize=2048)
def _word_regex(pattern: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Z0-9]){re.escape(pattern)}(?![A-Z0-9])")


def rule_matches(rule: Rule, normalised: str, amount: Decimal | None = None, direction: str | None = None) -> bool:
    # A rule with conditions only applies to a row whose amount and direction are known and fit.
    if rule.direction is not None and direction != rule.direction:
        return False
    if rule.min_amount is not None and (amount is None or amount < rule.min_amount):
        return False
    if rule.max_amount is not None and (amount is None or amount > rule.max_amount):
        return False
    if rule.pattern_type == "word":
        return _word_regex(rule.pattern.upper()).search(normalised) is not None
    return rule.pattern.upper() in normalised


def pick_rule(
    rules: list[Rule], normalised: str, amount: Decimal | None = None, direction: str | None = None
) -> Rule | None:
    """`rules` must be sorted strongest first (see load_rules)."""
    stem = None
    for rule in rules:
        if rule_matches(rule, normalised, amount, direction):
            return rule
        if rule.origin == "correction" and rule.conditions == 0:
            # A correction is saved under the stem, which skips number words: the stem "CRDLESDEP AECT"
            # is not a substring of "CRDLESDEP 0000769618638 AECT", yet it is the same description.
            if stem is None:
                stem = description_stem(normalised)
            if stem == rule.pattern:
                return rule
    return None


def load_rules(db: Session, user_id: int) -> list[Rule]:
    rows = db.scalars(
        select(ClassificationRule).where(
            ClassificationRule.user_id == user_id, ClassificationRule.enabled.is_(True)
        )
    ).all()
    rules = [
        Rule(
            r.id, r.pattern.upper(), r.pattern_type, r.category_id, r.origin, r.priority,
            r.min_amount, r.max_amount, r.direction,
        )
        for r in rows
    ]
    # strongest first; among equals the longer pattern, then the one with more conditions
    rules.sort(key=lambda r: (-r.priority, -len(r.pattern), -r.conditions, r.id))
    return rules


# --- defaults ---------------------------------------------------------------------------


def ensure_defaults(db: Session, user_id: int) -> None:
    """Create the built-in categories and rules for a user (and add new ones after an
    update). Idempotent; safe to call often."""
    key = f"categorization_defaults:{user_id}"
    setting = db.get(Setting, key)
    if setting is not None and int(setting.value or 0) >= SYSTEM_VERSION:
        return

    try:
        with db.begin_nested():  # a savepoint: a concurrent seeder must not poison the caller
            existing = {
                c.name: c for c in db.scalars(select(Category).where(Category.user_id == user_id))
            }
            for name, kind in CATEGORIES:
                if name not in existing:
                    category = Category(user_id=user_id, name=name, kind=kind, is_system=True)
                    db.add(category)
                    existing[name] = category
            db.flush()

            known = {
                (r.pattern_type, r.pattern.upper())
                for r in db.scalars(
                    select(ClassificationRule).where(ClassificationRule.user_id == user_id)
                )
            }
            for pattern, pattern_type, category_name, priority in RULES:
                if (pattern_type, pattern) not in known:
                    db.add(
                        ClassificationRule(
                            user_id=user_id,
                            pattern=pattern,
                            pattern_type=pattern_type,
                            category_id=existing[category_name].id,
                            origin="system",
                            priority=priority,
                        )
                    )
            if setting is None:
                db.add(Setting(key=key, value=SYSTEM_VERSION))
            else:
                setting.value = SYSTEM_VERSION
            db.flush()
    except IntegrityError:
        return  # another worker seeded at the same moment
    # New built-in rules must also reach the rows you already have (the version is current now, so
    # this call does not come back here). Manual choices and AI suggestions are left alone.
    if setting is not None:
        classify_rows(db, user_id)


# --- classification -----------------------------------------------------------------------


def classify_rows(
    db: Session,
    user_id: int,
    document_id: int | None = None,
    sources: tuple = REEVALUATE,
) -> int:
    """Apply the rules to rows that are not manually set. Returns how many rows changed.

    Does not commit; the caller owns the transaction.
    """
    ensure_defaults(db, user_id)
    rules = load_rules(db, user_id)

    query = select(
        Transaction.id,
        Transaction.original_description,
        Transaction.category_id,
        Transaction.classification_source,
        Transaction.classification_explanation,
        Transaction.debit,
        Transaction.credit,
    ).where(Transaction.user_id == user_id)
    if document_id is not None:
        query = query.where(Transaction.document_id == document_id)
    in_sources = [s for s in sources if s is not None]
    query = query.where(
        or_(Transaction.classification_source.is_(None), Transaction.classification_source.in_(in_sources))
    )

    updates: list[dict] = []
    applied: Counter = Counter()
    for row in db.execute(query):
        out = Decimal(row.debit) > 0
        rule = pick_rule(
            rules,
            normalise(row.original_description),
            Decimal(row.debit) if out else Decimal(row.credit),
            "out" if out else "in",
        )
        if rule:
            source = "rule" if rule.origin == "system" else "user_rule"
            explanation = f"Rule: {rule.pattern_type} '{rule.pattern}'"[:200]
            new = (rule.category_id, source, 1.0, explanation)
        elif row.classification_source == "llm_unsure":
            continue  # the model already looked and was unsure; leave it for review
        elif row.classification_source == "llm":
            continue  # an AI suggestion stays unless a rule now matches
        else:
            new = (None, None, None, None)

        current = (row.category_id, row.classification_source, row.classification_explanation)
        if (new[0], new[1], new[3]) == current:
            continue
        updates.append(
            {
                "id": row.id,
                "category_id": new[0],
                "classification_source": new[1],
                "classification_confidence": new[2],
                "classification_explanation": new[3],
            }
        )
        if rule:
            applied[rule.id] += 1

    for start in range(0, len(updates), _CHUNK):
        db.execute(update(Transaction), updates[start : start + _CHUNK])
    for rule_id, count in applied.items():
        db.execute(
            update(ClassificationRule)
            .where(ClassificationRule.id == rule_id)
            .values(hit_count=ClassificationRule.hit_count + count)
        )
    return len(updates)


# --- corrections and learning -----------------------------------------------------------------


def set_manual_category(
    db: Session, user_id: int, transaction: Transaction, category_id: int | None
) -> None:
    """You chose this category yourself. It is never overwritten by rules or the model."""
    previous = transaction.category_id
    transaction.category_id = category_id
    transaction.classification_source = "manual"
    transaction.classification_confidence = 1.0
    transaction.classification_explanation = "Set by you"
    db.add(
        ClassificationFeedback(
            user_id=user_id,
            transaction_id=transaction.id,
            from_category_id=previous,
            to_category_id=category_id,
        )
    )


def upsert_correction_rule(db: Session, user_id: int, stem: str, category_id: int) -> ClassificationRule:
    rule = db.scalar(
        select(ClassificationRule).where(
            ClassificationRule.user_id == user_id,
            ClassificationRule.pattern_type == "contains",
            ClassificationRule.pattern == stem,
            ClassificationRule.conditions_key == "",
        )
    )
    if rule is None:
        rule = ClassificationRule(
            user_id=user_id,
            pattern=stem,
            pattern_type="contains",
            category_id=category_id,
            origin="correction",
            priority=CORRECTION_PRIORITY,
        )
        db.add(rule)
    else:
        rule.category_id = category_id
        rule.enabled = True
        rule.priority = max(rule.priority, CORRECTION_PRIORITY)
    db.flush()
    return rule


def apply_stem(db: Session, user_id: int, stem: str, category_id: int) -> tuple[ClassificationRule, int]:
    """Create or update a rule for `stem` and apply it to every matching row that is not
    manually set (replacing built-in rule results and AI suggestions)."""
    rule = upsert_correction_rule(db, user_id, stem, category_id)
    changed = classify_rows(db, user_id, sources=OVERRIDE_AI)
    return rule, changed


def count_similar(db: Session, user_id: int, stem: str, exclude_id: int | None = None) -> int:
    """Other rows a rule for `stem` would affect (not manual, not already that rule's)."""
    needle = stem.upper()
    count = 0
    for row_id, description, source in db.execute(
        select(
            Transaction.id, Transaction.original_description, Transaction.classification_source
        ).where(Transaction.user_id == user_id)
    ):
        text = normalise(description)
        if row_id != exclude_id and source != "manual" and (needle in text or description_stem(text) == needle):
            count += 1
    return count


# --- review queue ---------------------------------------------------------------------------------


def review_groups(db: Session, user_id: int, limit: int = 100) -> tuple[list[dict], int]:
    """Uncategorised transactions grouped by stem, biggest groups first.

    Duplicates (the same transaction in an overlapping statement) are left out.
    """
    groups: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "example": None, "hints": Counter(), "confidence": {}, "reason": None}
    )
    total = 0
    for _id, description, suggested, source, confidence, explanation in db.execute(
        select(
            Transaction.id,
            Transaction.original_description,
            Transaction.suggested_category_id,
            Transaction.classification_source,
            Transaction.classification_confidence,
            Transaction.classification_explanation,
        ).where(
            Transaction.user_id == user_id,
            Transaction.is_duplicate.is_(False),
            Transaction.category_id.is_(None),
            or_(
                Transaction.classification_source.is_(None),
                Transaction.classification_source == "llm_unsure",
            ),
        )
    ):
        stem = description_stem(description)
        group = groups[stem]
        group["count"] += 1
        group["example"] = group["example"] or description
        if source == "llm_unsure" and suggested is not None:
            group["hints"][suggested] += 1
            group["confidence"][suggested] = confidence
            group["reason"] = explanation
        total += 1

    names = {c.id: c.name for c in db.scalars(select(Category).where(Category.user_id == user_id))}
    ordered = sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0]))[:limit]
    result = []
    for stem, g in ordered:
        hint_id = g["hints"].most_common(1)[0][0] if g["hints"] else None
        result.append(
            {
                "stem": stem,
                "count": g["count"],
                "example": g["example"],
                "hint_category_id": hint_id if hint_id in names else None,
                "hint_category_name": names.get(hint_id) if hint_id is not None else None,
                "hint_confidence": g["confidence"].get(hint_id) if hint_id is not None else None,
                "hint_reason": g["reason"] if hint_id is not None else None,
            }
        )
    return result, total


def classify_all_users(db: Session) -> int:
    """Categorise rows that existed before categories did. Idempotent; commits."""
    changed = 0
    for (user_id,) in db.execute(select(Transaction.user_id).distinct()).all():
        changed += classify_rows(db, user_id)
    db.commit()
    return changed
