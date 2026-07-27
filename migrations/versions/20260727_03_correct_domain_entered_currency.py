"""Correct entered currency for the derived SAREMI domain seed key.

Revision ID: 20260727_03
Revises: 20260727_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_03"
down_revision = "20260727_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
            UPDATE cost_items
            SET entered_unit_cost = 35, entered_currency = 'USD'
            WHERE id = 7
              AND cost_key = 'software.namecheap.saremi.domain.purchase'
              AND unit_cost = 630
              AND currency = 'MXN'
              AND entered_unit_cost = 630
              AND entered_currency = 'MXN'
            """))


def downgrade() -> None:
    op.execute(sa.text("""
            UPDATE cost_items
            SET entered_unit_cost = 630, entered_currency = 'MXN'
            WHERE id = 7
              AND cost_key = 'software.namecheap.saremi.domain.purchase'
              AND unit_cost = 630
              AND currency = 'MXN'
              AND entered_unit_cost = 35
              AND entered_currency = 'USD'
            """))
