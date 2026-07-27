from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


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
    __table_args__ = (UniqueConstraint("source_system", "source_event_id", name="uq_source_event"),)

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
    import_status: Mapped[str] = mapped_column(String(40), default="imported")
    classification_error: Mapped[str | None] = mapped_column(Text)


class EventClassificationORM(Base):
    """Local interpretation of an imported operational event.

    Populated by the classification engine (later phase). Created here so the
    ingestion foundation and the schema move together.
    """

    __tablename__ = "event_classifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    imported_event_id: Mapped[int] = mapped_column(ForeignKey("imported_operational_events.id"), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    service_code: Mapped[str | None] = mapped_column(String(80))
    usage_event_type: Mapped[str | None] = mapped_column(String(120))
    classification: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    is_billable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cost_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_client_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)


class EventImportCursorORM(Base):
    """Idempotent synchronization state per source system."""

    __tablename__ = "event_import_cursors"

    source_system: Mapped[str] = mapped_column(String(80), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(400))
    last_occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text)
