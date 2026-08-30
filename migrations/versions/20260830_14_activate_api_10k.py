"""Activate the SAREMI API 10K catalog plan.

Revision ID: 20260830_14
Revises: 20260830_13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260830_14"
down_revision = "20260830_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE pricing_plans SET status='active', assignable=1, assignment_requires_approval=0, "
            "processing_description='Motor API estándar de extracción y validación para alto volumen.', "
            "configuration_description='Integración mediante API documentada; sin capa operativa Platform.', "
            "support_description='Soporte prioritario.' "
            "WHERE plan_code='SAREMI_API_10K' AND version=1"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    assigned = connection.execute(
        sa.text("SELECT id FROM client_subscriptions WHERE pricing_plan_id=12 LIMIT 1")
    ).scalar_one_or_none()
    if assigned is not None:
        raise RuntimeError("Cannot deactivate API 10K while a subscription references it.")
    connection.execute(
        sa.text(
            "UPDATE pricing_plans SET status='informational', assignable=0, assignment_requires_approval=1, "
            "processing_description='Oferta API de alto volumen pendiente de validación de infraestructura.', "
            "configuration_description='Integración mediante API documentada; sin límites técnicos inventados.', "
            "support_description='Activación sujeta a revisión técnica y comercial.' "
            "WHERE plan_code='SAREMI_API_10K' AND version=1"
        )
    )
