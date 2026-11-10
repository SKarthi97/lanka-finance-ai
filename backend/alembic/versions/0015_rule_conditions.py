"""classification rules can also look at the amount and the direction

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("classification_rules", sa.Column("min_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("classification_rules", sa.Column("max_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("classification_rules", sa.Column("direction", sa.String(3), nullable=True))
    op.add_column(
        "classification_rules",
        sa.Column("conditions_key", sa.String(48), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_rules_pattern", "classification_rules", type_="unique")
    op.create_unique_constraint(
        "uq_rules_pattern",
        "classification_rules",
        ["user_id", "pattern_type", "pattern", "conditions_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_rules_pattern", "classification_rules", type_="unique")
    op.create_unique_constraint(
        "uq_rules_pattern", "classification_rules", ["user_id", "pattern_type", "pattern"]
    )
    op.drop_column("classification_rules", "conditions_key")
    op.drop_column("classification_rules", "direction")
    op.drop_column("classification_rules", "max_amount")
    op.drop_column("classification_rules", "min_amount")
