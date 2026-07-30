"""Add durable operational-event normalization schema.

Revision ID: 20260730_07
Revises: 20260727_06
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260730_07"
down_revision = "20260727_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())

    if "imported_operational_events" not in tables:
        _create_imported_events_table()
    else:
        _upgrade_imported_events_table(connection)

    tables = set(sa.inspect(connection).get_table_names())
    if "event_import_cursors" not in tables:
        _create_cursors_table()
    if "event_classifications" not in tables:
        _create_classifications_table()
    else:
        _upgrade_classifications_table(connection)
    if "usage_events" not in tables:
        _create_usage_events_table()
    else:
        _upgrade_usage_events_table(connection)


def _create_imported_events_table() -> None:
    op.create_table(
        "imported_operational_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("source_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("event_category", sa.String(80)),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("recorded_at", sa.DateTime()),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(120)),
        sa.Column("causation_id", sa.String(160)),
        sa.Column("external_reference_id", sa.String(160)),
        sa.Column("source_client_ref", sa.String(160)),
        sa.Column("entity_id", sa.String(160)),
        sa.Column("document_id", sa.String(160)),
        sa.Column("document_hash", sa.String(200)),
        sa.Column("property_id", sa.String(160)),
        sa.Column("profile_id", sa.String(160)),
        sa.Column("transaction_id", sa.String(200)),
        sa.Column("status", sa.String(40)),
        sa.Column("quantity", sa.Numeric(18, 6)),
        sa.Column("unit", sa.String(40)),
        sa.Column("raw_payload_json", sa.Text()),
        sa.Column("import_status", sa.String(40), nullable=False, server_default="imported"),
        sa.Column("classification_error", sa.Text()),
        sa.Column("classification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_system", "source_event_id", name="uq_source_event"),
        sa.CheckConstraint(
            "import_status IN ('imported', 'normalized', 'unresolved', 'skipped', 'failed')",
            name="ck_imported_operational_events_status",
        ),
    )
    op.create_index(
        "ix_imported_operational_events_source_status",
        "imported_operational_events",
        ["source_system", "import_status"],
    )


def _upgrade_imported_events_table(connection) -> None:
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("imported_operational_events")}
    if "classification_attempts" not in columns:
        op.add_column(
            "imported_operational_events",
            sa.Column("classification_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "classified_at" not in columns:
        op.add_column(
            "imported_operational_events",
            sa.Column("classified_at", sa.DateTime(timezone=True)),
        )
    if "import_status" not in columns:
        op.add_column(
            "imported_operational_events",
            sa.Column("import_status", sa.String(40), nullable=True),
        )
        op.execute(
            sa.text("UPDATE imported_operational_events SET import_status = 'imported' " "WHERE import_status IS NULL")
        )
        with op.batch_alter_table("imported_operational_events") as batch:
            batch.alter_column("import_status", existing_type=sa.String(40), nullable=False)
    elif any(
        column["name"] == "import_status" and column["nullable"]
        for column in inspector.get_columns("imported_operational_events")
    ):
        op.execute(
            sa.text("UPDATE imported_operational_events SET import_status = 'imported' " "WHERE import_status IS NULL")
        )
        with op.batch_alter_table("imported_operational_events") as batch:
            batch.alter_column("import_status", existing_type=sa.String(40), nullable=False)

    inspector = sa.inspect(connection)
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("imported_operational_events")}
    if "ck_imported_operational_events_status" not in checks:
        with op.batch_alter_table("imported_operational_events") as batch:
            batch.create_check_constraint(
                "ck_imported_operational_events_status",
                "import_status IN ('imported', 'normalized', 'unresolved', 'skipped', 'failed')",
            )
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("imported_operational_events")}
    if "ix_imported_operational_events_source_status" not in indexes:
        op.create_index(
            "ix_imported_operational_events_source_status",
            "imported_operational_events",
            ["source_system", "import_status"],
        )


def _create_cursors_table() -> None:
    op.create_table(
        "event_import_cursors",
        sa.Column("source_system", sa.String(80), primary_key=True),
        sa.Column("cursor", sa.String(400)),
        sa.Column("last_occurred_at", sa.DateTime()),
        sa.Column("last_successful_sync_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.Text()),
    )


def _create_classifications_table() -> None:
    op.create_table(
        "event_classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "imported_event_id",
            sa.Integer(),
            sa.ForeignKey("imported_operational_events.id"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id")),
        sa.Column("service_code", sa.String(80)),
        sa.Column("usage_event_type", sa.String(120)),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6)),
        sa.Column("unit", sa.String(40)),
        sa.Column("is_billable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_cost_relevant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_client_visible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_internal_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("classification_reason", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("rule_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("imported_event_id", name="uq_event_classifications_imported_event_id"),
    )


def _upgrade_classifications_table(connection) -> None:
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("event_classifications")}
    now = datetime.now(UTC)
    additions = {
        "rule_version": sa.Column("rule_version", sa.String(40), nullable=True),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("event_classifications", column)
    op.execute(
        sa.text(
            "UPDATE event_classifications SET "
            "classification = COALESCE(classification, 'unresolved'), "
            "rule_version = COALESCE(rule_version, 'legacy'), "
            "created_at = COALESCE(created_at, :now), "
            "updated_at = COALESCE(updated_at, :now)"
        ).bindparams(now=now)
    )
    inspector = sa.inspect(connection)
    unique_names = {constraint["name"] for constraint in inspector.get_unique_constraints("event_classifications")}
    with op.batch_alter_table("event_classifications") as batch:
        batch.alter_column("classification", existing_type=sa.String(40), nullable=False)
        batch.alter_column("rule_version", existing_type=sa.String(40), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        if "uq_event_classifications_imported_event_id" not in unique_names:
            batch.create_unique_constraint("uq_event_classifications_imported_event_id", ["imported_event_id"])


def _create_usage_events_table() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("service_code", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(), nullable=False),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("external_reference_id", sa.String(120)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("imported_event_id", sa.Integer(), sa.ForeignKey("imported_operational_events.id")),
        sa.UniqueConstraint("imported_event_id", name="uq_usage_events_imported_event_id"),
    )


def _upgrade_usage_events_table(connection) -> None:
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("usage_events")}
    unique_names = {constraint["name"] for constraint in inspector.get_unique_constraints("usage_events")}
    foreign_key_columns = {
        tuple(constraint["constrained_columns"]) for constraint in inspector.get_foreign_keys("usage_events")
    }
    with op.batch_alter_table("usage_events") as batch:
        if "imported_event_id" not in columns:
            batch.add_column(sa.Column("imported_event_id", sa.Integer(), nullable=True))
        if ("imported_event_id",) not in foreign_key_columns:
            batch.create_foreign_key(
                "fk_usage_events_imported_event_id",
                "imported_operational_events",
                ["imported_event_id"],
                ["id"],
            )
        if "uq_usage_events_imported_event_id" not in unique_names:
            batch.create_unique_constraint("uq_usage_events_imported_event_id", ["imported_event_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "event_classifications" in tables:
        op.drop_table("event_classifications")
    if "usage_events" in tables:
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("usage_events")}
        if "imported_event_id" in columns:
            with op.batch_alter_table("usage_events") as batch:
                batch.drop_column("imported_event_id")
    if "event_import_cursors" in tables:
        op.drop_table("event_import_cursors")
    if "imported_operational_events" in tables:
        op.drop_table("imported_operational_events")
