"""accounts, transactions, extraction columns on documents

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bank_id",
            sa.Integer,
            sa.ForeignKey("banks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("account_number_last4", sa.String(4), nullable=False),
        sa.Column("account_fingerprint", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="LKR"),
        sa.Column("nickname", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "bank_id", "account_fingerprint", name="uq_accounts_identity"
        ),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"])

    op.add_column(
        "documents",
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("period_start", sa.Date, nullable=True))
    op.add_column("documents", sa.Column("period_end", sa.Date, nullable=True))
    op.add_column("documents", sa.Column("opening_balance", sa.Numeric(18, 2), nullable=True))
    op.add_column("documents", sa.Column("closing_balance", sa.Numeric(18, 2), nullable=True))
    op.add_column("documents", sa.Column("adapter", sa.String(32), nullable=True))
    op.add_column("documents", sa.Column("adapter_version", sa.String(16), nullable=True))
    op.add_column("documents", sa.Column("extraction_confidence", sa.Float, nullable=True))
    op.add_column("documents", sa.Column("validation", JSONB, nullable=True))

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bank_id",
            sa.Integer,
            sa.ForeignKey("banks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("original_description", sa.Text, nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("running_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="LKR"),
        sa.Column("source_page", sa.Integer, nullable=False),
        sa.Column("validation_status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column(
            "extraction_method", sa.String(16), nullable=False, server_default="adapter"
        ),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("document_id", "seq", name="uq_transactions_doc_seq"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_document_id", "transactions", ["document_id"])
    op.create_index("ix_transactions_row_hash", "transactions", ["row_hash"])
    op.create_index(
        "ix_transactions_user_date", "transactions", ["user_id", "transaction_date"]
    )


def downgrade() -> None:
    op.drop_table("transactions")
    for column in (
        "validation",
        "extraction_confidence",
        "adapter_version",
        "adapter",
        "closing_balance",
        "opening_balance",
        "period_end",
        "period_start",
        "account_id",
    ):
        op.drop_column("documents", column)
    op.drop_index("ix_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")
