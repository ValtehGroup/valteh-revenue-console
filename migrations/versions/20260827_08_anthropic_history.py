"""Add persistent Anthropic usage and cost history.

Revision ID: 20260827_08
Revises: 20260730_07
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_08"
down_revision = "20260730_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anthropic_usage_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("api_key_id", sa.String(160), nullable=False),
        sa.Column("workspace_id", sa.String(160), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("service_tier", sa.String(80), nullable=False),
        sa.Column("uncached_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_creation_1h_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_creation_5m_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("web_search_requests", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "bucket_date",
            "api_key_id",
            "workspace_id",
            "model",
            "service_tier",
            name="uq_anthropic_usage_daily_identity",
        ),
    )
    op.create_index("ix_anthropic_usage_daily_date", "anthropic_usage_daily", ["bucket_date"])
    op.create_index(
        "ix_anthropic_usage_daily_api_key_date",
        "anthropic_usage_daily",
        ["api_key_id", "bucket_date"],
    )

    op.create_table(
        "anthropic_cost_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("workspace_id", sa.String(160), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("cost_type", sa.String(80), nullable=False),
        sa.Column("token_type", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(24, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "bucket_date",
            "workspace_id",
            "description",
            "model",
            "cost_type",
            "token_type",
            "currency",
            name="uq_anthropic_cost_daily_identity",
        ),
    )
    op.create_index("ix_anthropic_cost_daily_date", "anthropic_cost_daily", ["bucket_date"])
    op.create_index(
        "ix_anthropic_cost_daily_workspace_date",
        "anthropic_cost_daily",
        ["workspace_id", "bucket_date"],
    )

    op.create_table(
        "anthropic_api_keys",
        sa.Column("api_key_id", sa.String(160), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("workspace_id", sa.String(160), nullable=False),
        sa.Column("partial_key_hint", sa.String(80), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "anthropic_workspaces",
        sa.Column("workspace_id", sa.String(160), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "anthropic_api_key_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("api_key_id", sa.String(160), nullable=False),
        sa.Column("environment", sa.String(40), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("api_key_id", "effective_from", name="uq_anthropic_api_key_assignment_start"),
        sa.CheckConstraint(
            "environment IN ('development', 'staging', 'production', 'internal')",
            name="ck_anthropic_api_key_assignments_environment",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_anthropic_api_key_assignments_dates",
        ),
    )
    op.create_index(
        "ix_anthropic_api_key_assignments_key_dates",
        "anthropic_api_key_assignments",
        ["api_key_id", "effective_from", "effective_to"],
    )
    op.create_table(
        "anthropic_sync_watermarks",
        sa.Column("dataset", sa.String(20), primary_key=True),
        sa.Column("last_complete_date", sa.Date()),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dataset IN ('usage', 'cost')", name="ck_anthropic_sync_watermarks_dataset"),
    )
    op.create_table(
        "anthropic_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_start_date", sa.Date(), nullable=False),
        sa.Column("requested_end_date", sa.Date(), nullable=False),
        sa.Column("completed_start_date", sa.Date()),
        sa.Column("completed_end_date", sa.Date()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usage_rows_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_rows_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_usage_watermark", sa.Date()),
        sa.Column("resulting_usage_watermark", sa.Date()),
        sa.Column("previous_cost_watermark", sa.Date()),
        sa.Column("resulting_cost_watermark", sa.Date()),
        sa.Column("total_usage_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_billed_cost", sa.Numeric(24, 12), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint("mode IN ('bootstrap', 'incremental', 'repair')", name="ck_anthropic_sync_runs_mode"),
        sa.CheckConstraint("status IN ('succeeded', 'failed')", name="ck_anthropic_sync_runs_status"),
    )
    op.create_index("ix_anthropic_sync_runs_started_at", "anthropic_sync_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_anthropic_sync_runs_started_at", table_name="anthropic_sync_runs")
    op.drop_table("anthropic_sync_runs")
    op.drop_table("anthropic_sync_watermarks")
    op.drop_index(
        "ix_anthropic_api_key_assignments_key_dates",
        table_name="anthropic_api_key_assignments",
    )
    op.drop_table("anthropic_api_key_assignments")
    op.drop_table("anthropic_workspaces")
    op.drop_table("anthropic_api_keys")
    op.drop_index("ix_anthropic_cost_daily_workspace_date", table_name="anthropic_cost_daily")
    op.drop_index("ix_anthropic_cost_daily_date", table_name="anthropic_cost_daily")
    op.drop_table("anthropic_cost_daily")
    op.drop_index("ix_anthropic_usage_daily_api_key_date", table_name="anthropic_usage_daily")
    op.drop_index("ix_anthropic_usage_daily_date", table_name="anthropic_usage_daily")
    op.drop_table("anthropic_usage_daily")
