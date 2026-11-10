
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import (
    Category,
    Job,
    Transaction,
    UserSession,
)
from app.routers.ai import ProgressOut, progress_out
from app.routers.categories import _category_or_404, _error  # noqa: F401
from app.services import ai_activity, categorizer
from app.services.llm_classifier import (
    BATCH_SIZE,
    JOB_TYPE,
    MAX_STEMS_PER_JOB,
    enqueue_classification,
)

router = APIRouter(prefix="/api", tags=["categorization"])


# --- correcting one transaction ------------------------------------------------------------------


class CorrectionIn(BaseModel):
    category_id: int | None
    # Also learn a rule from this transaction and apply it to similar ones.
    create_rule: bool = False
    # Only report how many similar transactions there are; change nothing.
    preview: bool = False


class CorrectionOut(BaseModel):
    transaction_id: int
    category_id: int | None
    category_name: str | None
    stem: str
    similar_count: int  # other transactions the same rule would cover
    rule_id: int | None
    changed: int  # other transactions re-categorised


@router.put("/transactions/{transaction_id}/category", response_model=CorrectionOut)
def correct_transaction(
    transaction_id: int,
    body: CorrectionIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> CorrectionOut:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.user_id != session.user_id:
        raise _error(404, "not_found", "Transaction not found.")

    category = None
    if body.category_id is not None:
        category = _category_or_404(db, session.user_id, body.category_id)
    if body.create_rule and category is None:
        raise _error(422, "category_required", "Choose a category to create a rule.")

    stem = categorizer.description_stem(transaction.original_description)
    if body.preview:
        return CorrectionOut(
            transaction_id=transaction.id,
            category_id=body.category_id,
            category_name=category.name if category else None,
            stem=stem,
            similar_count=categorizer.count_similar(
                db, session.user_id, stem, exclude_id=transaction.id
            ),
            rule_id=None,
            changed=0,
        )

    categorizer.set_manual_category(db, session.user_id, transaction, body.category_id)

    rule_id, changed = None, 0
    if body.create_rule and category is not None:
        db.flush()
        rule, changed = categorizer.apply_stem(db, session.user_id, stem, category.id)
        rule_id = rule.id

    similar = categorizer.count_similar(db, session.user_id, stem, exclude_id=transaction.id)
    db.commit()
    return CorrectionOut(
        transaction_id=transaction.id,
        category_id=body.category_id,
        category_name=category.name if category else None,
        stem=stem,
        similar_count=0 if body.create_rule else similar,
        rule_id=rule_id,
        changed=changed,
    )


# --- review queue and the AI pass ------------------------------------------------------------------


class ReviewGroup(BaseModel):
    stem: str
    count: int
    example: str
    # A low-confidence AI guess: offered as a one-click choice, never applied on its own.
    hint_category_id: int | None = None
    hint_category_name: str | None = None
    hint_confidence: float | None = None
    hint_reason: str | None = None  # for example "Similar to 4 descriptions you categorised"


class ReviewOut(BaseModel):
    total: int
    groups: list[ReviewGroup]


class ApplyIn(BaseModel):
    stem: str = Field(min_length=2, max_length=128)
    category_id: int


class ApplyOut(BaseModel):
    rule_id: int
    changed: int


class StatusOut(BaseModel):
    ai_enabled: bool
    ai_pending: bool
    uncategorised: int
    progress: ProgressOut


@router.get("/categorization/review", response_model=ReviewOut)
def review_queue(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> ReviewOut:
    categorizer.ensure_defaults(db, session.user_id)
    db.commit()
    groups, total = categorizer.review_groups(db, session.user_id)
    return ReviewOut(total=total, groups=[ReviewGroup(**g) for g in groups])


@router.post("/categorization/apply", response_model=ApplyOut)
def apply_to_group(
    body: ApplyIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApplyOut:
    """Give every transaction matching this description one category, and remember it."""
    category = _category_or_404(db, session.user_id, body.category_id)
    rule, changed = categorizer.apply_stem(
        db, session.user_id, categorizer.normalise(body.stem), category.id
    )
    db.commit()
    return ApplyOut(rule_id=rule.id, changed=changed)


@router.post("/categorization/reclassify")
def reclassify(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> dict:
    changed = categorizer.classify_rows(db, session.user_id)
    db.commit()
    return {"changed": changed}


@router.get("/categorization/status", response_model=StatusOut)
def status(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StatusOut:
    pending = db.scalars(
        select(Job).where(Job.type == JOB_TYPE, Job.status.in_(("queued", "running")))
    ).all()
    uncategorised = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.user_id == session.user_id,
            Transaction.is_duplicate.is_(False),
            Transaction.category_id.is_(None),
            or_(
                Transaction.classification_source.is_(None),
                Transaction.classification_source == "llm_unsure",
            ),
        )
    )
    return StatusOut(
        ai_enabled=settings.llm_classify_enabled,
        ai_pending=any((j.payload or {}).get("user_id") == session.user_id for j in pending),
        uncategorised=uncategorised or 0,
        progress=progress_out(
            ai_activity.progress(
                db,
                session.user_id,
                JOB_TYPE,
                "categorize",
                ai_activity.categorise_waiting(db, session.user_id),
                BATCH_SIZE,
                MAX_STEMS_PER_JOB,
            )
        ),
    )


@router.post("/categorization/ai", status_code=202)
def ask_ai(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Queue the local model to suggest categories for what the rules left over."""
    if not settings.llm_classify_enabled:
        raise _error(409, "ai_disabled", "AI categorisation is turned off.")
    # Rows the model judged unsure get another chance after you ask again.
    db.execute(
        Transaction.__table__.update()
        .where(
            Transaction.user_id == session.user_id,
            Transaction.classification_source == "llm_unsure",
        )
        .values(classification_source=None)
    )
    queued = enqueue_classification(db, settings, session.user_id)
    db.commit()
    return {"queued": queued}


# --- bulk change and AI suggestions ----------------------------------------------------------------


MAX_BULK = 500


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK)
    category_id: int | None  # None clears the category


class BulkOut(BaseModel):
    changed: int


@router.post("/transactions/bulk-category", response_model=BulkOut)
def bulk_category(
    body: BulkIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> BulkOut:
    """Set one category on several transactions at once (each counts as set by you).

    No rule is learned: a selection is a hand-picked set, not a pattern. Use the Review tab
    or the question after a single change to teach a rule.
    """
    if body.category_id is not None:
        _category_or_404(db, session.user_id, body.category_id)
    rows = db.scalars(
        select(Transaction).where(
            Transaction.user_id == session.user_id, Transaction.id.in_(set(body.ids))
        )
    ).all()
    for transaction in rows:
        categorizer.set_manual_category(db, session.user_id, transaction, body.category_id)
    db.commit()
    return BulkOut(changed=len(rows))


# --- AI suggestions: accept or reject in bulk ------------------------------------------------------


class SuggestionGroup(BaseModel):
    stem: str
    category_id: int
    category_name: str
    count: int
    example: str
    confidence: float  # the lowest in the group


class SuggestionsOut(BaseModel):
    total: int
    confident_threshold: float  # "accept all confident" covers groups at or above this
    groups: list[SuggestionGroup]


class SuggestionIn(BaseModel):
    stem: str = Field(min_length=2, max_length=128)
    category_id: int


@router.get("/categorization/suggestions", response_model=SuggestionsOut)
def suggestions(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SuggestionsOut:
    """What the local AI applied, grouped by description and suggested category."""
    groups: dict[tuple[str, int], dict] = {}
    names: dict[int, str] = {}
    total = 0
    for description, category_id, confidence, name in db.execute(
        select(
            Transaction.original_description,
            Transaction.category_id,
            Transaction.classification_confidence,
            Category.name,
        )
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == session.user_id,
            Transaction.is_duplicate.is_(False),
            Transaction.classification_source == "llm",
        )
    ):
        stem = categorizer.description_stem(description)
        group = groups.setdefault(
            (stem, category_id),
            {"count": 0, "example": description, "confidence": 1.0},
        )
        group["count"] += 1
        group["confidence"] = min(group["confidence"], confidence if confidence is not None else 1.0)
        names[category_id] = name
        total += 1

    ordered = sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0][0]))
    return SuggestionsOut(
        total=total,
        confident_threshold=settings.llm_confident_threshold,
        groups=[
            SuggestionGroup(
                stem=stem,
                category_id=category_id,
                category_name=names[category_id],
                count=g["count"],
                example=g["example"],
                confidence=round(g["confidence"], 2),
            )
            for (stem, category_id), g in ordered
        ],
    )


@router.post("/categorization/suggestions/accept", response_model=ApplyOut)
def accept_suggestion(
    body: SuggestionIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApplyOut:
    """Accept an AI suggestion for every transaction with this description, and remember it
    as a rule so future statements follow it without the model."""
    category = _category_or_404(db, session.user_id, body.category_id)
    rule, changed = categorizer.apply_stem(
        db, session.user_id, categorizer.normalise(body.stem), category.id
    )
    db.commit()
    return ApplyOut(rule_id=rule.id, changed=changed)


@router.post("/categorization/suggestions/reject", response_model=BulkOut)
def reject_suggestion(
    body: SuggestionIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> BulkOut:
    """Take back an AI suggestion: those transactions return to the review queue."""
    _category_or_404(db, session.user_id, body.category_id)
    stem = categorizer.normalise(body.stem)
    changed = 0
    for transaction in db.scalars(
        select(Transaction).where(
            Transaction.user_id == session.user_id,
            Transaction.classification_source == "llm",
            Transaction.category_id == body.category_id,
        )
    ):
        if categorizer.description_stem(transaction.original_description) == stem:
            transaction.category_id = None
            transaction.classification_source = None
            transaction.classification_confidence = None
            transaction.classification_explanation = None
            changed += 1
    db.commit()
    return BulkOut(changed=changed)
