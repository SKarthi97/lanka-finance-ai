"""merchant_names: clean names per description stem

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_names",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stem", sa.String(200), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "stem", name="uq_merchant_names_stem"),
    )


def downgrade() -> None:
    op.drop_table("merchant_names")
