"""Persistence and read models for SAREMI usage-event snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.client_repository import ClientRepository
from app.data.database import SessionLocal
from app.data.schemas import SaremiSyncWatermarkORM, SaremiUsageEventORM, UsageEventORM
from app.domain.saremi_usage import POLICY_VERSION, SaremiUsageEvent, classify_saremi_event, redact_saremi_payload

SAREMI_SOURCE = "saremi"
SAREMI_STREAM = "saremi.usage_events"


@dataclass
class SaremiUpsertSummary:
    received: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    normalized: int = 0
    unresolved: int = 0


@dataclass(frozen=True)
class SaremiSyncStatus:
    status: str
    high_watermark: datetime | None
    last_successful_sync_at: datetime | None
    error_message: str | None
    total_facts: int
    normalized_facts: int
    unresolved_facts: int


class SaremiUsageRepository:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    @staticmethod
    def upsert_events(
        session: Session,
        events: Iterable[SaremiUsageEvent],
        *,
        observed_at: datetime,
        billable_unit_confirmed: bool,
    ) -> SaremiUpsertSummary:
        summary = SaremiUpsertSummary()
        for event in events:
            summary.received += 1
            row = session.scalar(
                select(SaremiUsageEventORM).where(SaremiUsageEventORM.source_event_id == event.event_id)
            )
            if row is None:
                row = SaremiUsageEventORM(
                    source_event_id=event.event_id,
                    verification_id=event.verification_id,
                    document_type=event.document_type,
                    operation=event.operation,
                    source_status=event.status,
                    source_created_at=event.created_at,
                    source_updated_at=event.updated_at,
                    raw_payload_json="{}",
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    lifecycle_status="unclassified",
                    classification_status="unclassified",
                    classification_reason="Awaiting local classification.",
                    policy_version=POLICY_VERSION,
                )
                session.add(row)
                summary.inserted += 1
                should_apply = True
            else:
                row.last_seen_at = observed_at
                should_apply = _as_utc(event.updated_at) > _as_utc(row.source_updated_at)
                if should_apply:
                    summary.updated += 1
                else:
                    summary.unchanged += 1
            if not should_apply:
                continue
            _apply_source_snapshot(row, event)
            session.flush()
            outcome = _classify_and_normalize(
                session,
                row,
                event,
                billable_unit_confirmed=billable_unit_confirmed,
            )
            if outcome == "normalized":
                summary.normalized += 1
            elif outcome in {"unresolved", "unclassified"}:
                summary.unresolved += 1
        return summary

    @staticmethod
    def reclassify_stored_events(session: Session, *, billable_unit_confirmed: bool) -> SaremiUpsertSummary:
        """Reapply current mappings/policy without another SAREMI request."""

        summary = SaremiUpsertSummary()
        rows = session.scalars(select(SaremiUsageEventORM).order_by(SaremiUsageEventORM.id)).all()
        for row in rows:
            summary.received += 1
            event = SaremiUsageEvent.model_validate(json.loads(row.raw_payload_json))
            outcome = _classify_and_normalize(
                session,
                row,
                event,
                billable_unit_confirmed=billable_unit_confirmed,
            )
            if outcome == "normalized":
                summary.normalized += 1
            elif outcome in {"unresolved", "unclassified"}:
                summary.unresolved += 1
        return summary

    def status(self) -> SaremiSyncStatus:
        with self._session_factory() as session:
            watermark = session.get(SaremiSyncWatermarkORM, SAREMI_STREAM)
            totals = dict(
                session.execute(
                    select(SaremiUsageEventORM.classification_status, func.count()).group_by(
                        SaremiUsageEventORM.classification_status
                    )
                ).all()
            )
            return SaremiSyncStatus(
                status=watermark.status if watermark else "not_started",
                high_watermark=watermark.high_watermark if watermark else None,
                last_successful_sync_at=watermark.last_successful_sync_at if watermark else None,
                error_message=watermark.error_message if watermark else None,
                total_facts=sum(totals.values()),
                normalized_facts=totals.get("normalized", 0),
                unresolved_facts=totals.get("unresolved", 0) + totals.get("unclassified", 0),
            )

    def list_events(self, *, limit: int = 500) -> list[dict]:
        """Return promoted, browser-safe fields only; never return raw payloads."""

        with self._session_factory() as session:
            rows = session.scalars(
                select(SaremiUsageEventORM)
                .order_by(SaremiUsageEventORM.source_updated_at.desc(), SaremiUsageEventORM.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "event_id": row.source_event_id,
                    "verification_id": row.verification_id,
                    "institution_id": row.institution_id or "",
                    "document_type": row.document_type,
                    "operation": row.operation,
                    "source_status": row.source_status,
                    "environment": row.source_environment or "Unknown",
                    "completed_at": row.source_completed_at.isoformat() if row.source_completed_at else "",
                    "updated_at": row.source_updated_at.isoformat(),
                    "lifecycle_status": row.lifecycle_status,
                    "classification_status": row.classification_status,
                    "classification_reason": row.classification_reason,
                }
                for row in rows
            ]


def _apply_source_snapshot(row: SaremiUsageEventORM, event: SaremiUsageEvent) -> None:
    raw = redact_saremi_payload(event.model_dump(mode="json"))
    row.verification_id = event.verification_id
    row.institution_id = event.institution_id
    row.institution_name = event.institution_name
    row.api_key_id = event.api_key_id
    row.api_key_name = event.api_key_name
    row.document_type = event.document_type
    row.operation = event.operation
    row.source_status = event.status
    row.source_environment = event.environment
    row.source_created_at = event.created_at
    row.source_completed_at = event.completed_at
    row.source_updated_at = event.updated_at
    row.ai_usage_summary_json = _json(event.ai_usage_summary) if event.ai_usage_summary is not None else None
    row.raw_payload_json = _json(raw)


def _classify_and_normalize(
    session: Session,
    row: SaremiUsageEventORM,
    event: SaremiUsageEvent,
    *,
    billable_unit_confirmed: bool,
) -> str:
    client_id = None
    if event.institution_id:
        client_id = ClientRepository.resolve_client_reference_in_session(
            session,
            SAREMI_SOURCE,
            event.institution_id,
        )
    classification = classify_saremi_event(
        event,
        client_id=client_id,
        billable_unit_confirmed=billable_unit_confirmed,
    )
    row.lifecycle_status = classification.lifecycle_status
    row.classification_status = classification.classification_status
    row.classification_reason = classification.reason
    row.policy_version = POLICY_VERSION

    usage = session.get(UsageEventORM, row.normalized_usage_event_id) if row.normalized_usage_event_id else None
    if classification.classification_status != "eligible" or client_id is None:
        if usage is not None:
            row.normalized_usage_event_id = None
            session.delete(usage)
        return classification.classification_status

    duplicate = session.scalar(
        select(UsageEventORM).where(
            UsageEventORM.source_system == SAREMI_SOURCE,
            UsageEventORM.billable_unit_id == event.verification_id,
            UsageEventORM.id != (usage.id if usage else -1),
        )
    )
    if duplicate is not None:
        row.classification_status = "unresolved"
        row.classification_reason = "The SAREMI verification_id is already linked to another usage fact."
        if usage is not None:
            row.normalized_usage_event_id = None
            session.delete(usage)
        return "unresolved"

    metadata = {
        "document_type": event.document_type,
        "institution_id": event.institution_id,
        "operation": event.operation,
        "policy_version": POLICY_VERSION,
        "source_event_id": event.event_id,
        "source_status": event.status,
        "source_updated_at": event.updated_at.isoformat(),
    }
    values = {
        "client_id": client_id,
        "service_code": "saremi",
        "event_type": "saremi.processed_document",
        "quantity": 1,
        "unit": "document",
        "event_timestamp": event.completed_at,
        "source_system": SAREMI_SOURCE,
        "external_reference_id": event.event_id[:120],
        "metadata_json": _json(metadata),
        "data_origin": "production",
        "environment": "production",
        "is_billable": True,
        "billable_unit_id": event.verification_id,
    }
    if usage is None:
        usage = UsageEventORM(**values)
        session.add(usage)
        session.flush()
        row.normalized_usage_event_id = usage.id
    else:
        for key, value in values.items():
            setattr(usage, key, value)
    row.classification_status = "normalized"
    row.classification_reason = "Normalized as one production SAREMI processed document."
    return "normalized"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
