"""categories, classification rules and feedback, model runs, transaction classification

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _user_fk() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, _user_fk(), nullable=False),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
    )
    op.create_index("ix_categories_user_id", "categories", ["user_id"])

    op.create_table(
        "classification_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, _user_fk(), nullable=False),
        sa.Column("pattern_type", sa.String(16), nullable=False, server_default="contains"),
        sa.Column("pattern", sa.String(128), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(16), nullable=False, server_default="user"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="10"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "pattern_type", "pattern", name="uq_rules_pattern"),
    )
    op.create_index("ix_classification_rules_user_id", "classification_rules", ["user_id"])

    op.create_table(
        "classification_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, _user_fk(), nullable=False),
        sa.Column(
            "transaction_id",
            sa.Integer,
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "from_category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rule_id",
            sa.Integer,
            sa.ForeignKey("classification_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_classification_feedback_user_id", "classification_feedback", ["user_id"])

    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("digest", sa.String(128), nullable=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("valid_json", sa.Boolean, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "transactions",
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.add_column(
        "transactions", sa.Column("classification_source", sa.String(16), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("classification_confidence", sa.Float, nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("classification_explanation", sa.String(200), nullable=True)
    )


def downgrade() -> None:
    for column in (
        "classification_explanation",
        "classification_confidence",
        "classification_source",
    ):
        op.drop_column("transactions", column)
    op.drop_index("ix_transactions_category_id", table_name="transactions")
    op.drop_column("transactions", "category_id")
    op.drop_table("model_runs")
    op.drop_index("ix_classification_feedback_user_id", table_name="classification_feedback")
    op.drop_table("classification_feedback")
    op.drop_index("ix_classification_rules_user_id", table_name="classification_rules")
    op.drop_table("classification_rules")
    op.drop_index("ix_categories_user_id", table_name="categories")
    op.drop_table("categories")
