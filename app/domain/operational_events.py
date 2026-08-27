"""Shared operational event contract.

Pydantic models mirroring `docs/shared-operational-event-contract.md`. Source
systems (`baas-qro`, `rpp-fraud-detection-system`, future `sigen-plus-front`)
emit operational facts only. Economic interpretation happens elsewhere in this
app, never in these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class OperationalEvent(BaseModel):
    """A single operational fact exported by a source system.

    Only operational fields are accepted. Any economic field that leaks in from
    a source system (price, cost, revenue, margin, invoice, plan, ...) is ignored
    on purpose: this model does not declare them and forbids extras.
    """

    model_config = ConfigDict(extra="forbid")

    # Required common fields.
    id: str
    source_system: str
    event_type: str
    event_category: str
    occurred_at: datetime
    recorded_at: datetime
    status: str
    correlation_id: str
    schema_version: str = SCHEMA_VERSION

    # Optional common fields. Only those used by the current ingestion pipeline
    # are declared explicitly; the rest travel inside ``metadata``.
    causation_id: str | None = None
    idempotency_key: str | None = None
    actor_user_id: str | None = None
    actor_email: str | None = None
    actor_type: str | None = None
    client_reference: str | None = None
    entity_id: str | None = None
    notary_office_id: str | None = None
    property_id: str | None = None
    folio_real: str | None = None
    registry_matter_id: str | None = None
    document_id: str | None = None
    document_type: str | None = None
    document_hash: str | None = None
    certificate_id: str | None = None
    profile_id: str | None = None
    person_id: str | None = None
    fraud_alert_id: str | None = None
    fraud_alert_type: str | None = None
    severity: str | None = None
    risk_score: float | None = None
    validation_provider: str | None = None
    validation_status: str | None = None
    validation_confidence: float | None = None
    blockchain_id: str | None = None
    chaincode_name: str | None = None
    chaincode_function: str | None = None
    channel_name: str | None = None
    transaction_id: str | None = None
    block_number: int | None = None
    external_reference_id: str | None = None
    quantity: float | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class OperationalEventPagination(BaseModel):
    """Cursor pagination block returned by a source export endpoint."""

    next_cursor: str | None = None
    has_more: bool = False


class OperationalEventPage(BaseModel):
    """One page of an operational-events export response."""

    data: list[OperationalEvent]
    pagination: OperationalEventPagination = Field(default_factory=OperationalEventPagination)
    invalid_event_errors: list[str] = Field(default_factory=list, exclude=True)
