"""Add the dedicated Notaría 38 pilot pricing plan.

Revision ID: 20260827_09
Revises: 20260827_08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_09"
down_revision = "20260827_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pricing_plans") as batch:
        batch.add_column(sa.Column("dedicated_client_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_pricing_plans_dedicated_client_id_clients",
            "clients",
            ["dedicated_client_id"],
            ["id"],
        )

    pricing_plans = sa.table(
        "pricing_plans",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("dedicated_client_id", sa.Integer()),
        sa.column("setup_fee", sa.Numeric()),
        sa.column("annual_fee", sa.Numeric()),
        sa.column("monthly_fixed_fee", sa.Numeric()),
        sa.column("included_documents", sa.Integer()),
        sa.column("included_validations", sa.Integer()),
        sa.column("included_graph_queries", sa.Integer()),
        sa.column("included_blockchain_transactions", sa.Integer()),
        sa.column("price_per_document", sa.Numeric()),
        sa.column("price_per_validation", sa.Numeric()),
        sa.column("price_per_graph_query", sa.Numeric()),
        sa.column("price_per_blockchain_transaction", sa.Numeric()),
        sa.column("price_per_property_mint", sa.Numeric()),
        sa.column("revenue_share_percentage", sa.Numeric()),
    )
    op.bulk_insert(
        pricing_plans,
        [
            {
                "id": 5,
                "name": "Notaría 38 Pilot (Ad hoc)",
                "dedicated_client_id": 1,
                "setup_fee": 5000,
                "annual_fee": 0,
                "monthly_fixed_fee": 0,
                "included_documents": 500,
                "included_validations": 0,
                "included_graph_queries": 0,
                "included_blockchain_transactions": 0,
                "price_per_document": 0,
                "price_per_validation": 0,
                "price_per_graph_query": 0,
                "price_per_blockchain_transaction": 0,
                "price_per_property_mint": 0,
                "revenue_share_percentage": 0,
            }
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM pricing_plans WHERE id = 5"))
    with op.batch_alter_table("pricing_plans") as batch:
        batch.drop_constraint("fk_pricing_plans_dedicated_client_id_clients", type_="foreignkey")
        batch.drop_column("dedicated_client_id")
