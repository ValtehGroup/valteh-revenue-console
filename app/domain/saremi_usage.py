"""SAREMI provider contract and conservative local usage policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

POLICY_VERSION = "2026-09-05.1"
ELIGIBLE_TERMINAL_STATUSES = frozenset({"verified", "invalid", "inconclusive"})
SUPPORTED_OPERATION = "document_verification"
SOURCE_ENVIRONMENT_MAP = {
    "production": "production",
    "test": "sandbox",
    "sandbox": "sandbox",
    "staging": "staging",
    "development": "development",
    "internal": "internal",
}


class SaremiUsageEvent(BaseModel):
    """Stable core of one mutable SAREMI usage-event snapshot.

    Extra fields are intentionally accepted and retained in the redacted raw
    payload so additive source changes do not stop synchronization.
    """

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(min_length=1, max_length=160)
    verification_id: str = Field(min_length=1, max_length=160)
    institution_id: str | None = Field(default=None, max_length=160)
    institution_name: str | None = Field(default=None, max_length=240)
    api_key_id: str | None = Field(default=None, max_length=160)
    api_key_name: str | None = Field(default=None, max_length=240)
    document_type: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=120)
    created_at: datetime
    completed_at: datetime | None = None
    updated_at: datetime
    environment: str | None = None
    ai_usage_summary: dict[str, Any] | None = None

    @field_validator("event_id", "verification_id", "document_type", "operation", "status")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("created_at", "completed_at", "updated_at")
    @classmethod
    def require_timezone_and_convert_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SAREMI timestamps must include timezone information")
        return value.astimezone(UTC)


class SaremiUsagePageEnvelope(BaseModel):
    """Top-level SAREMI pagination envelope; event rows are parsed separately."""

    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]]
    next_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True)
class SaremiClassification:
    lifecycle_status: str
    classification_status: str
    reason: str
    revenue_environment: str | None = None


def classify_saremi_event(
    event: SaremiUsageEvent,
    *,
    client_id: int | None,
    billable_unit_confirmed: bool,
) -> SaremiClassification:
    """Apply the versioned Revenue policy without rewriting provider status."""

    normalized_status = event.status.strip().lower()
    if normalized_status == "processing":
        return _classification("in_progress", "non_billable", "SAREMI processing is not terminal.")
    if normalized_status == "manual_review":
        return _classification(
            "review_required",
            "non_billable",
            "SAREMI manual_review is non-billable until commercial policy is approved.",
        )
    if normalized_status == "failed":
        return _classification("failed", "non_billable", "SAREMI failed is a terminal technical failure.")
    if normalized_status not in ELIGIBLE_TERMINAL_STATUSES:
        return _classification(
            "unclassified",
            "unclassified",
            f"Unknown SAREMI status '{event.status}' has no local billing rule.",
        )
    if event.operation != SUPPORTED_OPERATION:
        return _classification(
            "completed",
            "unclassified",
            f"Unsupported SAREMI operation '{event.operation}'.",
        )
    if event.completed_at is None:
        return _classification("completed", "unresolved", "A terminal verification has no completed_at timestamp.")
    source_environment = (event.environment or "").strip().lower()
    revenue_environment = SOURCE_ENVIRONMENT_MAP.get(source_environment)
    if revenue_environment is None:
        reason = (
            "SAREMI environment is missing; production must not be inferred."
            if not source_environment
            else f"Unknown SAREMI environment '{event.environment}'."
        )
        return _classification("completed", "unresolved", reason)
    if revenue_environment != "production":
        return _classification(
            "completed",
            "non_billable",
            f"SAREMI environment '{event.environment}' maps to non-production '{revenue_environment}'.",
            revenue_environment,
        )
    if not event.institution_id:
        return _classification("completed", "unresolved", "SAREMI institution_id is missing.", revenue_environment)
    if client_id is None:
        return _classification(
            "completed",
            "unresolved",
            f"No enabled Revenue client mapping exists for SAREMI institution '{event.institution_id}'.",
            revenue_environment,
        )
    if not billable_unit_confirmed:
        return _classification(
            "completed",
            "unresolved",
            "SAREMI verification_id has not been confirmed as the stable billable unit.",
            revenue_environment,
        )
    return _classification(
        "completed",
        "eligible",
        "All SAREMI production usage guards passed.",
        revenue_environment,
    )


def redact_saremi_payload(value: Any) -> Any:
    """Redact likely credentials/PII from forward-compatible raw payloads."""

    if isinstance(value, list):
        return [redact_saremi_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else redact_saremi_payload(item)
        for key, item in value.items()
    }


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    exact = {
        "authorization",
        "access_token",
        "refresh_token",
        "api_key",
        "password",
        "secret",
        "document_content",
        "document_contents",
        "document_text",
        "extracted_text",
        "checks",
        "email",
        "phone",
        "filename",
        "file_name",
        "file_path",
        "path",
        "ip",
        "ip_address",
    }
    return normalized in exact or normalized.endswith("_secret") or normalized.endswith("_token")


def _classification(
    lifecycle: str,
    status: str,
    reason: str,
    environment: str | None = None,
) -> SaremiClassification:
    return SaremiClassification(lifecycle, status, reason, environment)
