"""Add persisted USD/MXN FIX history.

Revision ID: 20260829_11
Revises: 20260827_10
"""

import sqlalchemy as sa
from alembic import op

revision = "20260829_11"
down_revision = "20260827_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usd_mxn_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("series_id", sa.String(40), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("series_id", "rate_date", name="uq_usd_mxn_rates_series_date"),
        sa.CheckConstraint("rate > 0", name="ck_usd_mxn_rates_positive_rate"),
    )
    op.create_index(
        "ix_usd_mxn_rates_series_date",
        "usd_mxn_rates",
        ["series_id", "rate_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_usd_mxn_rates_series_date", table_name="usd_mxn_rates")
    op.drop_table("usd_mxn_rates")
