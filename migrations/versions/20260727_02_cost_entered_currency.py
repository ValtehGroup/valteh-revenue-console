"""Preserve entered cost amount and currency separately from normalized MXN.

Revision ID: 20260727_02
Revises: 20260727_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_02"
down_revision = "20260727_01"
branch_labels = None
depends_on = None


USD_SEED_COSTS = (
    (2, "infrastructure.hetzner", "32", "576"),
    (3, "software.microsoft365.team", "6", "108"),
    (4, "software.microsoft365.team", "8", "144"),
    (5, "software.github.enterprise", "4", "72"),
    (7, "software.namecheap.saremi.domain.purchase", "35", "630"),
    (8, "software.claude.anthropic", "17", "306"),
)


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("cost_items")}
    if "entered_unit_cost" not in columns:
        op.add_column("cost_items", sa.Column("entered_unit_cost", sa.Numeric(12, 6), nullable=True))
    if "entered_currency" not in columns:
        op.add_column("cost_items", sa.Column("entered_currency", sa.String(3), nullable=True))

    op.execute(sa.text("UPDATE cost_items SET entered_unit_cost = unit_cost WHERE entered_unit_cost IS NULL"))
    op.execute(sa.text("UPDATE cost_items SET entered_currency = currency WHERE entered_currency IS NULL"))
    for record_id, cost_key, entered_cost, normalized_cost in USD_SEED_COSTS:
        op.execute(
            sa.text("""
                UPDATE cost_items
                SET entered_unit_cost = :entered_cost, entered_currency = 'USD'
                WHERE id = :record_id
                  AND cost_key = :cost_key
                  AND unit_cost = :normalized_cost
                  AND currency = 'MXN'
                  AND entered_unit_cost = unit_cost
                  AND entered_currency = currency
                """).bindparams(
                record_id=record_id,
                cost_key=cost_key,
                entered_cost=entered_cost,
                normalized_cost=normalized_cost,
            )
        )

    checks = {constraint["name"] for constraint in sa.inspect(connection).get_check_constraints("cost_items")}
    with op.batch_alter_table("cost_items") as batch:
        batch.alter_column("entered_unit_cost", existing_type=sa.Numeric(12, 6), nullable=False)
        batch.alter_column("entered_currency", existing_type=sa.String(3), nullable=False)
        if "ck_cost_items_entered_unit_cost_non_negative" not in checks:
            batch.create_check_constraint("ck_cost_items_entered_unit_cost_non_negative", "entered_unit_cost >= 0")


def downgrade() -> None:
    with op.batch_alter_table("cost_items") as batch:
        batch.drop_constraint("ck_cost_items_entered_unit_cost_non_negative", type_="check")
        batch.drop_column("entered_currency")
        batch.drop_column("entered_unit_cost")
