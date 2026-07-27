"""Add durable client management and external references.

Revision ID: 20260727_05
Revises: 20260727_04
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260727_05"
down_revision = "20260727_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    now = datetime.now(UTC)

    if "clients" not in tables:
        _create_clients_table()
    else:
        columns = {column["name"] for column in inspector.get_columns("clients")}
        if "client_code" not in columns:
            op.add_column("clients", sa.Column("client_code", sa.String(40), nullable=True))
        if "end_date" not in columns:
            op.add_column("clients", sa.Column("end_date", sa.Date(), nullable=True))
        if "created_at" not in columns:
            op.add_column("clients", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        if "updated_at" not in columns:
            op.add_column("clients", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

        for client_id in connection.scalars(sa.text("SELECT id FROM clients ORDER BY id")).all():
            op.execute(
                sa.text(
                    "UPDATE clients SET client_code = :client_code, "
                    "created_at = COALESCE(created_at, :now), updated_at = COALESCE(updated_at, :now) "
                    "WHERE id = :client_id"
                ).bindparams(client_code=f"client_{client_id:04d}", now=now, client_id=client_id)
            )

        checks = {constraint["name"] for constraint in sa.inspect(connection).get_check_constraints("clients")}
        with op.batch_alter_table("clients") as batch:
            batch.alter_column("client_code", existing_type=sa.String(40), nullable=False)
            batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
            batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
            if "ck_clients_status" not in checks:
                batch.create_check_constraint("ck_clients_status", "status IN ('active', 'inactive')")
            if "ck_clients_dates" not in checks:
                batch.create_check_constraint("ck_clients_dates", "end_date IS NULL OR end_date >= start_date")
        indexes = {index["name"] for index in sa.inspect(connection).get_indexes("clients")}
        if "ix_clients_client_code" not in indexes:
            op.create_index("ix_clients_client_code", "clients", ["client_code"], unique=True)
        if "ix_clients_updated_at" not in indexes:
            op.create_index("ix_clients_updated_at", "clients", ["updated_at"])

    tables = set(sa.inspect(connection).get_table_names())
    if "pricing_plans" not in tables:
        _create_pricing_plans_table()
    if "client_subscriptions" not in tables:
        _create_client_subscriptions_table()
    if "client_external_references" not in tables:
        op.create_table(
            "client_external_references",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("source_system", sa.String(80), nullable=False),
            sa.Column("external_client_reference", sa.String(160), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "source_system",
                "external_client_reference",
                name="uq_client_external_reference_source_value",
            ),
        )
        op.create_index(
            "ix_client_external_references_client_id", "client_external_references", ["client_id"]
        )
        op.create_index(
            "ix_client_external_references_source_value",
            "client_external_references",
            ["source_system", "external_client_reference"],
        )


def _create_clients_table() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("client_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_clients_status"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_clients_dates"),
    )
    op.create_index("ix_clients_client_code", "clients", ["client_code"], unique=True)
    op.create_index("ix_clients_updated_at", "clients", ["updated_at"])


def _create_pricing_plans_table() -> None:
    op.create_table(
        "pricing_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("setup_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("annual_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("monthly_fixed_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("included_documents", sa.Integer(), server_default="0"),
        sa.Column("included_validations", sa.Integer(), server_default="0"),
        sa.Column("included_graph_queries", sa.Integer(), server_default="0"),
        sa.Column("included_blockchain_transactions", sa.Integer(), server_default="0"),
        sa.Column("price_per_document", sa.Numeric(12, 2), server_default="0"),
        sa.Column("price_per_validation", sa.Numeric(12, 2), server_default="0"),
        sa.Column("price_per_graph_query", sa.Numeric(12, 2), server_default="0"),
        sa.Column("price_per_blockchain_transaction", sa.Numeric(12, 2), server_default="0"),
        sa.Column("price_per_property_mint", sa.Numeric(12, 2), server_default="0"),
        sa.Column("revenue_share_percentage", sa.Numeric(5, 4), server_default="0"),
    )


def _create_client_subscriptions_table() -> None:
    op.create_table(
        "client_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("pricing_plan_id", sa.Integer(), sa.ForeignKey("pricing_plans.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("status", sa.String(40), server_default="active"),
        sa.Column("notes", sa.Text()),
    )


def downgrade() -> None:
    op.drop_index("ix_client_external_references_source_value", table_name="client_external_references")
    op.drop_index("ix_client_external_references_client_id", table_name="client_external_references")
    op.drop_table("client_external_references")
    with op.batch_alter_table("clients") as batch:
        batch.drop_index("ix_clients_updated_at")
        batch.drop_index("ix_clients_client_code")
        batch.drop_constraint("ck_clients_dates", type_="check")
        batch.drop_constraint("ck_clients_status", type_="check")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
        batch.drop_column("end_date")
        batch.drop_column("client_code")
