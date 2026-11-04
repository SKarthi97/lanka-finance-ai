"""Add Hatton National Bank to the supported banks.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO banks (code, name) "
        "SELECT 'hnb', 'Hatton National Bank' "
        "WHERE NOT EXISTS (SELECT 1 FROM banks WHERE code = 'hnb')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM banks WHERE code = 'hnb' AND id NOT IN (SELECT bank_id FROM documents WHERE bank_id IS NOT NULL)")
