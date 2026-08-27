"""Remove the superseded July Notaría 38 pilot subscription.

Revision ID: 20260827_10
Revises: 20260827_09
"""

from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "20260827_10"
down_revision = "20260827_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM client_subscriptions "
            "WHERE id = 1 AND client_id = 1 AND pricing_plan_id = 1 "
            "AND start_date = '2026-07-01' AND end_date = '2026-07-31'"
        )
    )


def downgrade() -> None:
    subscriptions = sa.table(
        "client_subscriptions",
        sa.column("id", sa.Integer()),
        sa.column("client_id", sa.Integer()),
        sa.column("pricing_plan_id", sa.Integer()),
        sa.column("start_date", sa.Date()),
        sa.column("end_date", sa.Date()),
        sa.column("status", sa.String()),
        sa.column("notes", sa.Text()),
    )
    op.bulk_insert(
        subscriptions,
        [
            {
                "id": 1,
                "client_id": 1,
                "pricing_plan_id": 1,
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
                "status": "inactive",
                "notes": "Notaria 38 pilot on SIGEN Pilot. Fees come from seed_pricing_plans.csv.",
            }
        ],
    )
