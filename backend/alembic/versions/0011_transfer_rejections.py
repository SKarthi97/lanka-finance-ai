"""transfer_rejections: pairs of rows the user said are not own-account transfers

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_rejections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("hash_a", sa.String(64), nullable=False),
        sa.Column("hash_b", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "hash_a", "hash_b", name="uq_transfer_rejections_pair"),
    )


def downgrade() -> None:
    op.drop_table("transfer_rejections")
