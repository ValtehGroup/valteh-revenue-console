"""Add mutable SAREMI usage facts and synchronization audit state.

Revision ID: 20260905_15
Revises: 20260830_14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260905_15"
down_revision = "20260830_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saremi_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_unchanged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_invalid", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_normalized", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_unresolved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("resulting_watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saremi_sync_runs_started_at", "saremi_sync_runs", ["started_at"])

    op.create_table(
        "saremi_sync_watermarks",
        sa.Column("stream", sa.String(length=80), nullable=False),
        sa.Column("cursor", sa.String(length=500), nullable=True),
        sa.Column("query_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("query_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("high_watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="idle", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("stream"),
    )

    op.create_table(
        "saremi_usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.String(length=160), nullable=False),
        sa.Column("verification_id", sa.String(length=160), nullable=False),
        sa.Column("institution_id", sa.String(length=160), nullable=True),
        sa.Column("institution_name", sa.String(length=240), nullable=True),
        sa.Column("api_key_id", sa.String(length=160), nullable=True),
        sa.Column("api_key_name", sa.String(length=240), nullable=True),
        sa.Column("document_type", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("source_status", sa.String(length=120), nullable=False),
        sa.Column("source_environment", sa.String(length=80), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ai_usage_summary_json", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=40), nullable=False),
        sa.Column("classification_status", sa.String(length=40), nullable=False),
        sa.Column("classification_reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("normalized_usage_event_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["normalized_usage_event_id"], ["usage_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_usage_event_id", name="uq_saremi_usage_events_normalized_usage_event_id"),
        sa.UniqueConstraint("source_event_id", name="uq_saremi_usage_events_source_event_id"),
    )
    op.create_index(
        "ix_saremi_usage_events_classification",
        "saremi_usage_events",
        ["classification_status"],
    )
    op.create_index(
        "ix_saremi_usage_events_institution_updated",
        "saremi_usage_events",
        ["institution_id", "source_updated_at"],
    )
    op.create_index(
        "ix_saremi_usage_events_status_updated", "saremi_usage_events", ["source_status", "source_updated_at"]
    )
    op.create_index("ix_saremi_usage_events_verification_id", "saremi_usage_events", ["verification_id"])


def downgrade() -> None:
    op.drop_index("ix_saremi_usage_events_verification_id", table_name="saremi_usage_events")
    op.drop_index("ix_saremi_usage_events_status_updated", table_name="saremi_usage_events")
    op.drop_index("ix_saremi_usage_events_institution_updated", table_name="saremi_usage_events")
    op.drop_index("ix_saremi_usage_events_classification", table_name="saremi_usage_events")
    op.drop_table("saremi_usage_events")
    op.drop_table("saremi_sync_watermarks")
    op.drop_index("ix_saremi_sync_runs_started_at", table_name="saremi_sync_runs")
    op.drop_table("saremi_sync_runs")
