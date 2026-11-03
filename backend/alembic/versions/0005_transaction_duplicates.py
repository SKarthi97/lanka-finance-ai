"""transactions.is_duplicate, duplicate_of_id

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "duplicate_of_id",
            sa.Integer,
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Existing rows are flagged by the worker at startup (app.services.dedupe), which keeps
    # this migration schema-only.


def downgrade() -> None:
    op.drop_column("transactions", "duplicate_of_id")
    op.drop_column("transactions", "is_duplicate")
