"""Add cost audit timestamps and management indexes.

Revision ID: 20260727_01
Revises:
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260727_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "cost_items" not in inspector.get_table_names():
        op.create_table(
            "cost_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cost_key", sa.String(120), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("provider", sa.String(120)),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("service_line", sa.String(80)),
            sa.Column("cost_type", sa.String(40), nullable=False),
            sa.Column("charge_basis", sa.String(80), nullable=False),
            sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="1"),
            sa.Column("unit_cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(80), nullable=False),
            sa.Column("billing_frequency", sa.String(40), nullable=False),
            sa.Column("start_date", sa.Date()),
            sa.Column("end_date", sa.Date()),
            sa.Column("currency", sa.String(3), nullable=False, server_default="MXN"),
            sa.Column("record_type", sa.String(40), nullable=False, server_default="actual"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("quantity >= 0", name="ck_cost_items_quantity_non_negative"),
            sa.CheckConstraint("unit_cost >= 0", name="ck_cost_items_unit_cost_non_negative"),
            sa.CheckConstraint(
                "end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_cost_items_dates"
            ),
        )
        op.create_index("ix_cost_items_cost_key", "cost_items", ["cost_key"])
        op.create_index("ix_cost_items_updated_at", "cost_items", ["updated_at"])
        op.create_index("ix_cost_items_enabled_record_type", "cost_items", ["enabled", "record_type"])
        op.create_index("ix_cost_items_effective_dates", "cost_items", ["start_date", "end_date"])
        return
    columns = {column["name"] for column in inspector.get_columns("cost_items")}
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("cost_items")}
    now = datetime.now(UTC)
    if "created_at" not in columns:
        op.add_column("cost_items", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text("UPDATE cost_items SET created_at = :now").bindparams(now=now))
    if "updated_at" not in columns:
        op.add_column("cost_items", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text("UPDATE cost_items SET updated_at = :now").bindparams(now=now))
    with op.batch_alter_table("cost_items") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        if "ck_cost_items_quantity_non_negative" not in checks:
            batch.create_check_constraint("ck_cost_items_quantity_non_negative", "quantity >= 0")
        if "ck_cost_items_unit_cost_non_negative" not in checks:
            batch.create_check_constraint("ck_cost_items_unit_cost_non_negative", "unit_cost >= 0")
        if "ck_cost_items_dates" not in checks:
            batch.create_check_constraint(
                "ck_cost_items_dates", "end_date IS NULL OR start_date IS NULL OR end_date >= start_date"
            )
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("cost_items")}
    if "ix_cost_items_updated_at" not in indexes:
        op.create_index("ix_cost_items_updated_at", "cost_items", ["updated_at"])
    if "ix_cost_items_cost_key" not in indexes:
        op.create_index("ix_cost_items_cost_key", "cost_items", ["cost_key"])
    if "ix_cost_items_enabled_record_type" not in indexes:
        op.create_index("ix_cost_items_enabled_record_type", "cost_items", ["enabled", "record_type"])
    if "ix_cost_items_effective_dates" not in indexes:
        op.create_index("ix_cost_items_effective_dates", "cost_items", ["start_date", "end_date"])


def downgrade() -> None:
    with op.batch_alter_table("cost_items") as batch:
        batch.drop_index("ix_cost_items_effective_dates")
        batch.drop_index("ix_cost_items_enabled_record_type")
        batch.drop_index("ix_cost_items_updated_at")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
