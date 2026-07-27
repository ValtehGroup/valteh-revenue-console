"""Model one-time costs as fixed costs billed once.

Revision ID: 20260727_04
Revises: 20260727_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_04"
down_revision = "20260727_03"
branch_labels = None
depends_on = None


TYPE_FREQUENCY_CHECK = (
    "(cost_type = 'variable' AND billing_frequency = 'usage') OR "
    "(cost_type = 'fixed' AND billing_frequency IN ('monthly', 'annual', 'once'))"
)


def upgrade() -> None:
    connection = op.get_bind()
    op.execute(sa.text("UPDATE cost_items SET cost_type = 'fixed', billing_frequency = 'once' "
                       "WHERE cost_type = 'one_time'"))

    invalid_ids = connection.scalars(
        sa.text(
            "SELECT id FROM cost_items WHERE NOT "
            "((cost_type = 'variable' AND billing_frequency = 'usage') OR "
            "(cost_type = 'fixed' AND billing_frequency IN ('monthly', 'annual', 'once')))"
        )
    ).all()
    if invalid_ids:
        formatted_ids = ", ".join(str(record_id) for record_id in invalid_ids)
        raise ValueError(f"Correct invalid cost type/frequency combinations for record IDs: {formatted_ids}")

    checks = {constraint["name"] for constraint in sa.inspect(connection).get_check_constraints("cost_items")}
    if "ck_cost_items_type_frequency" not in checks:
        with op.batch_alter_table("cost_items") as batch:
            batch.create_check_constraint("ck_cost_items_type_frequency", TYPE_FREQUENCY_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("cost_items") as batch:
        batch.drop_constraint("ck_cost_items_type_frequency", type_="check")
    op.execute(
        sa.text("UPDATE cost_items SET cost_type = 'one_time' WHERE cost_type = 'fixed' AND billing_frequency = 'once'")
    )
