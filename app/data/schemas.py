from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ClientORM(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_clients_status"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_clients_dates"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ClientExternalReferenceORM(Base):
    __tablename__ = "client_external_references"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "external_client_reference", name="uq_client_external_reference_source_value"
        ),
        Index("ix_client_external_references_client_id", "client_id"),
        Index(
            "ix_client_external_references_source_value",
            "source_system",
            "external_client_reference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    external_client_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ServiceORM(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    service_line: Mapped[str] = mapped_column(String(80), nullable=False)


class PricingPlanORM(Base):
    __tablename__ = "pricing_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dedicated_client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    setup_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    annual_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    monthly_fixed_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    included_documents: Mapped[int] = mapped_column(default=0)
    included_validations: Mapped[int] = mapped_column(default=0)
    included_graph_queries: Mapped[int] = mapped_column(default=0)
    included_blockchain_transactions: Mapped[int] = mapped_column(default=0)
    price_per_document: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_per_validation: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_per_graph_query: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_per_blockchain_transaction: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    price_per_property_mint: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    revenue_share_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)


class ClientSubscriptionORM(Base):
    __tablename__ = "client_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    pricing_plan_id: Mapped[int] = mapped_column(ForeignKey("pricing_plans.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), default="active")
    notes: Mapped[str | None] = mapped_column(Text)


class UsageEventORM(Base):
    __tablename__ = "usage_events"
    __table_args__ = (UniqueConstraint("imported_event_id", name="uq_usage_events_imported_event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    service_code: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    external_reference_id: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    imported_event_id: Mapped[int | None] = mapped_column(ForeignKey("imported_operational_events.id"))


class CostItemORM(Base):
    __tablename__ = "cost_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_cost_items_quantity_non_negative"),
        CheckConstraint("unit_cost >= 0", name="ck_cost_items_unit_cost_non_negative"),
        CheckConstraint("entered_unit_cost >= 0", name="ck_cost_items_entered_unit_cost_non_negative"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_cost_items_dates"),
        CheckConstraint(
            "(cost_type = 'variable' AND billing_frequency = 'usage') OR "
            "(cost_type = 'fixed' AND billing_frequency IN ('monthly', 'annual', 'once'))",
            name="ck_cost_items_type_frequency",
        ),
        Index("ix_cost_items_enabled_record_type", "enabled", "record_type"),
        Index("ix_cost_items_effective_dates", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cost_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    service_line: Mapped[str | None] = mapped_column(String(80))
    cost_type: Mapped[str] = mapped_column(String(40), nullable=False)
    charge_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    entered_unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    billing_frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    entered_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    record_type: Mapped[str] = mapped_column(String(40), default="actual")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RevenueEventORM(Base):
    __tablename__ = "revenue_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    service_code: Mapped[str] = mapped_column(String(80), nullable=False)
    revenue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ScenarioAssumptionORM(Base):
    __tablename__ = "scenario_assumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(80), nullable=False)
    assumption_key: Mapped[str] = mapped_column(String(120), nullable=False)
    assumption_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ImportedOperationalEventORM(Base):
    """Raw operational facts imported from source systems.

    Stores source events exactly as received, after minimal validation. Economic
    interpretation never mutates these rows; classification and normalization
    produce separate records. See docs/event-consumption-architecture.md.
    """

    __tablename__ = "imported_operational_events"
    __table_args__ = (
        UniqueConstraint("source_system", "source_event_id", name="uq_source_event"),
        CheckConstraint(
            "import_status IN ('imported', 'normalized', 'unresolved', 'skipped', 'failed')",
            name="ck_imported_operational_events_status",
        ),
        Index("ix_imported_operational_events_source_status", "source_system", "import_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    event_category: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    correlation_id: Mapped[str | None] = mapped_column(String(120))
    causation_id: Mapped[str | None] = mapped_column(String(160))
    external_reference_id: Mapped[str | None] = mapped_column(String(160))
    source_client_ref: Mapped[str | None] = mapped_column(String(160))
    entity_id: Mapped[str | None] = mapped_column(String(160))
    document_id: Mapped[str | None] = mapped_column(String(160))
    document_hash: Mapped[str | None] = mapped_column(String(200))
    property_id: Mapped[str | None] = mapped_column(String(160))
    profile_id: Mapped[str | None] = mapped_column(String(160))
    transaction_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    import_status: Mapped[str] = mapped_column(String(40), default="imported", nullable=False)
    classification_error: Mapped[str | None] = mapped_column(Text)
    classification_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventClassificationORM(Base):
    """Local interpretation of an imported operational event.

    Populated by the classification engine (later phase). Created here so the
    ingestion foundation and the schema move together.
    """

    __tablename__ = "event_classifications"
    __table_args__ = (UniqueConstraint("imported_event_id", name="uq_event_classifications_imported_event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_event_id: Mapped[int] = mapped_column(ForeignKey("imported_operational_events.id"), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    service_code: Mapped[str | None] = mapped_column(String(80))
    usage_event_type: Mapped[str | None] = mapped_column(String(120))
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    is_billable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cost_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_client_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventImportCursorORM(Base):
    """Idempotent synchronization state per source system."""

    __tablename__ = "event_import_cursors"

    source_system: Mapped[str] = mapped_column(String(80), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(400))
    last_occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text)


class AnthropicUsageDailyORM(Base):
    """Immutable-grain daily usage facts returned by Anthropic."""

    __tablename__ = "anthropic_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "bucket_date",
            "api_key_id",
            "workspace_id",
            "model",
            "service_tier",
            name="uq_anthropic_usage_daily_identity",
        ),
        Index("ix_anthropic_usage_daily_date", "bucket_date"),
        Index("ix_anthropic_usage_daily_api_key_date", "api_key_id", "bucket_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bucket_date: Mapped[date] = mapped_column(Date, nullable=False)
    api_key_id: Mapped[str] = mapped_column(String(160), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    service_tier: Mapped[str] = mapped_column(String(80), nullable=False)
    uncached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_creation_1h_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_creation_5m_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    web_search_requests: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicCostDailyORM(Base):
    """Daily billed-cost facts in provider currency, before API-key allocation."""

    __tablename__ = "anthropic_cost_daily"
    __table_args__ = (
        UniqueConstraint(
            "bucket_date",
            "workspace_id",
            "description",
            "model",
            "cost_type",
            "token_type",
            "currency",
            name="uq_anthropic_cost_daily_identity",
        ),
        Index("ix_anthropic_cost_daily_date", "bucket_date"),
        Index("ix_anthropic_cost_daily_workspace_date", "workspace_id", "bucket_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bucket_date: Mapped[date] = mapped_column(Date, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    cost_type: Mapped[str] = mapped_column(String(80), nullable=False)
    token_type: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicAPIKeyORM(Base):
    __tablename__ = "anthropic_api_keys"

    api_key_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    partial_key_hint: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicWorkspaceORM(Base):
    __tablename__ = "anthropic_workspaces"

    workspace_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicAPIKeyAssignmentORM(Base):
    """Date-effective client and environment ownership for an Anthropic API key."""

    __tablename__ = "anthropic_api_key_assignments"
    __table_args__ = (
        UniqueConstraint("api_key_id", "effective_from", name="uq_anthropic_api_key_assignment_start"),
        CheckConstraint(
            "environment IN ('development', 'staging', 'production', 'internal')",
            name="ck_anthropic_api_key_assignments_environment",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_anthropic_api_key_assignments_dates",
        ),
        Index(
            "ix_anthropic_api_key_assignments_key_dates",
            "api_key_id",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[str] = mapped_column(String(160), nullable=False)
    environment: Mapped[str] = mapped_column(String(40), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicSyncWatermarkORM(Base):
    __tablename__ = "anthropic_sync_watermarks"
    __table_args__ = (CheckConstraint("dataset IN ('usage', 'cost')", name="ck_anthropic_sync_watermarks_dataset"),)

    dataset: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_complete_date: Mapped[date | None] = mapped_column(Date)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnthropicSyncRunORM(Base):
    __tablename__ = "anthropic_sync_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('bootstrap', 'incremental', 'repair')", name="ck_anthropic_sync_runs_mode"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="ck_anthropic_sync_runs_status"),
        Index("ix_anthropic_sync_runs_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_start_date: Mapped[date | None] = mapped_column(Date)
    completed_end_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usage_rows_fetched: Mapped[int] = mapped_column(nullable=False, default=0)
    usage_rows_inserted: Mapped[int] = mapped_column(nullable=False, default=0)
    usage_rows_updated: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_rows_fetched: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_rows_inserted: Mapped[int] = mapped_column(nullable=False, default=0)
    cost_rows_updated: Mapped[int] = mapped_column(nullable=False, default=0)
    previous_usage_watermark: Mapped[date | None] = mapped_column(Date)
    resulting_usage_watermark: Mapped[date | None] = mapped_column(Date)
    previous_cost_watermark: Mapped[date | None] = mapped_column(Date)
    resulting_cost_watermark: Mapped[date | None] = mapped_column(Date)
    total_usage_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_billed_cost: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    error_message: Mapped[str | None] = mapped_column(Text)
