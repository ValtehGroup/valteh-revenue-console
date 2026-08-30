"""Align Platform setup pricing and remove the Scale badge.

Revision ID: 20260830_13
Revises: 20260830_12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260830_13"
down_revision = "20260830_12"
branch_labels = None
depends_on = None


def _assert_unassigned(connection) -> None:
    assigned = connection.execute(
        sa.text("SELECT pricing_plan_id FROM client_subscriptions WHERE pricing_plan_id IN (8, 9) LIMIT 1")
    ).scalar_one_or_none()
    if assigned is not None:
        raise RuntimeError(
            "Cannot update the pre-launch Scale/Enterprise catalog in place because a subscription references it."
        )


def upgrade() -> None:
    connection = op.get_bind()
    _assert_unassigned(connection)
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET setup_fee=9999, minimum_setup_fee=9999 "
            "WHERE plan_code IN ('SAREMI_CORE', 'SAREMI_SCALE', 'SAREMI_ENTERPRISE') AND version=1"
        )
    )
    connection.execute(
        sa.text("UPDATE pricing_plans SET featured_label=NULL WHERE plan_code='SAREMI_SCALE' AND version=1")
    )
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET setup_type='implementation' WHERE plan_code='SAREMI_ENTERPRISE' AND version=1"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    _assert_unassigned(connection)
    connection.execute(
        sa.text("UPDATE pricing_plans SET minimum_setup_fee=6999 WHERE plan_code='SAREMI_CORE' AND version=1")
    )
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET setup_fee=17999, minimum_setup_fee=14999, featured_label='Más popular' "
            "WHERE plan_code='SAREMI_SCALE' AND version=1"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET setup_fee=NULL, minimum_setup_fee=NULL, setup_type='custom' "
            "WHERE plan_code='SAREMI_ENTERPRISE' AND version=1"
        )
    )
