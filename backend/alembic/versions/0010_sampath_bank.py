"""Add Sampath Bank to the supported banks.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO banks (code, name) "
        "SELECT 'sampath', 'Sampath Bank' "
        "WHERE NOT EXISTS (SELECT 1 FROM banks WHERE code = 'sampath')"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM banks WHERE code = 'sampath' "
        "AND id NOT IN (SELECT bank_id FROM documents WHERE bank_id IS NOT NULL)"
    )
