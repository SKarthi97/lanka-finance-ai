from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres, plain JSON elsewhere (unit tests run on SQLite).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Only the SHA-256 of the cookie token is stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JsonType, nullable=True
    )


class Bank(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Duplicate protection: the same file (by content hash) once per user.
        UniqueConstraint("user_id", "sha256", name="uq_documents_user_sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("banks.id", ondelete="SET NULL"), nullable=True
    )
    # SHA-256 of the file exactly as uploaded (before any decryption).
    sha256: Mapped[str] = mapped_column(String(64))
    # Relative to DOCUMENTS_DIR. Encrypted PDFs are stored decrypted.
    storage_path: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    # queued -> processing -> inspected -> processing -> reconciled | needs_review | failed
    # needs_review -> accepted (user decision)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    adapter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Computed from the validation checks, never self-reported by a model.
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {"reconciled": bool, "checks": {...}, "issues": [{"code","page","seq"}]}; codes only.
    validation: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    # Set when the stored PDF was removed after successful processing.
    file_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    bank: Mapped[Bank | None] = relationship()
    account: Mapped["Account | None"] = relationship()


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_no", name="uq_document_pages_doc_page"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_no: Mapped[int] = mapped_column(Integer)
    # text | mixed | scanned | empty
    kind: Mapped[str] = mapped_column(String(16))
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    # Never put secrets (e.g. PDF passwords) or statement contents here.
    payload: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "bank_id", "account_fingerprint", name="uq_accounts_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("banks.id", ondelete="SET NULL"), nullable=True
    )
    # The full account number is never stored (see app/services/accounts.py).
    account_number_last4: Mapped[str] = mapped_column(String(4))
    account_fingerprint: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="LKR")
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("document_id", "seq", name="uq_transactions_doc_seq"),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("banks.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    transaction_date: Mapped[date] = mapped_column(Date)
    original_description: Mapped[str] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    running_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LKR")
    source_page: Mapped[int] = mapped_column(Integer)
    # ok | balance_mismatch | needs_review
    validation_status: Mapped[str] = mapped_column(String(16), default="ok")
    extraction_method: Mapped[str] = mapped_column(String(16), default="adapter")
    # sha256 of (account, date, debit, credit, balance, normalised description):
    # the dedupe key from docs/00-architecture.md section 4, used in Phase 5.
    row_hash: Mapped[str] = mapped_column(String(64), index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # rule (built-in) | user_rule (a rule you made) | manual (you set it) | llm | llm_unsure
    classification_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why: the rule pattern or "AI suggestion". Generic text only, never statement content.
    classification_explanation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # A low-confidence AI guess (source llm_unsure): shown as a hint in Review, never applied.
    suggested_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped["Category | None"] = relationship(foreign_keys=[category_id])
    # Set when the same transaction also appears in another statement (overlapping
    # periods). Duplicates stay visible but are excluded from every total.
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # income | expense | transfer. Transfers are excluded from income and expense totals.
    kind: Mapped[str] = mapped_column(String(16))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ClassificationRule(Base):
    __tablename__ = "classification_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "pattern_type", "pattern", "conditions_key", name="uq_rules_pattern"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # contains: pattern appears anywhere. word: pattern appears as a whole word.
    pattern_type: Mapped[str] = mapped_column(String(16), default="contains")
    pattern: Mapped[str] = mapped_column(String(128))
    # Optional conditions on the amount and direction ("in" = a credit, "out" = a debit). Empty = no condition.
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # direction|min|max as text, so the same words with different conditions are different rules
    conditions_key: Mapped[str] = mapped_column(String(48), default="", server_default="")
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    # system (built in) | user (you wrote it) | correction (learned from a fix)
    origin: Mapped[str] = mapped_column(String(16), default="user")
    # Higher wins; ties go to the longer (more specific) pattern.
    priority: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ClassificationFeedback(Base):
    __tablename__ = "classification_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    from_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    to_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_rules.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelRun(Base):
    """One call to the local model. Stores a hash of the prompt, never the text."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(128))
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purpose: Mapped[str] = mapped_column(String(32))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    valid_json: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TransferRejection(Base):
    """A pair of rows you said are NOT a transfer between your own accounts.

    Stored by row hash (not row id) so it still holds after a statement is extracted again.
    `hash_a` is always the smaller hash of the pair.
    """

    __tablename__ = "transfer_rejections"
    __table_args__ = (
        UniqueConstraint("user_id", "hash_a", "hash_b", name="uq_transfer_rejections_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    hash_a: Mapped[str] = mapped_column(String(64))
    hash_b: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Budget(Base):
    """A monthly spending limit for one category."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", name="uq_budgets_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class SavedView(Base):
    """A named set of Transactions filters. Holds filter values only, never rows."""

    __tablename__ = "saved_views"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_views_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    filters: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MerchantName(Base):
    """A clean name for a description stem, kept beside the original description.

    Keyed by stem (the reusable part of a description), not by transaction, so it applies to
    every row with that stem, survives a statement being extracted again, and covers future
    statements. `source`: llm (local model) or manual (you typed it; never overwritten).
    """

    __tablename__ = "merchant_names"
    __table_args__ = (UniqueConstraint("user_id", "stem", name="uq_merchant_names_stem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    stem: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class StemEmbedding(Base):
    """A description stem turned into a vector by the local embedding model.

    Keyed by (user, stem, model), so a different embedding model never reuses old vectors.
    `vector` is float32 bytes of a unit-length vector. Only the stem is embedded: never amounts,
    dates, accounts or filenames.
    """

    __tablename__ = "stem_embeddings"
    __table_args__ = (
        UniqueConstraint("user_id", "stem", "model", name="uq_stem_embeddings"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    stem: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
