"""Add Commercial Bank to the supported banks.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO banks (code, name) "
        "SELECT 'commercial', 'Commercial Bank' "
        "WHERE NOT EXISTS (SELECT 1 FROM banks WHERE code = 'commercial')"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM banks WHERE code = 'commercial' "
        "AND id NOT IN (SELECT bank_id FROM documents WHERE bank_id IS NOT NULL)"
    )
