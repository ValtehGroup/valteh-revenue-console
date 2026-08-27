from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.data.database import SessionLocal
from app.data.schemas import (
    AnthropicAPIKeyORM,
    AnthropicCostDailyORM,
    AnthropicSyncRunORM,
    AnthropicSyncWatermarkORM,
    AnthropicUsageDailyORM,
    AnthropicWorkspaceORM,
)
from app.integrations.anthropic_admin_api import (
    AnthropicAdminReport,
    AnthropicAPIKeyMetadata,
    AnthropicCostRow,
    AnthropicWorkspaceMetadata,
    MessagesUsageRow,
)

USAGE_DATASET = "usage"
COST_DATASET = "cost"
USD = "USD"

UsageIdentity = tuple[date, str, str, str, str]
CostIdentity = tuple[date, str, str, str, str, str, str]
SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class AnthropicWatermarks:
    usage: date | None = None
    cost: date | None = None


@dataclass(frozen=True)
class UpsertCounts:
    inserted: int
    updated: int


@dataclass(frozen=True)
class PersistedSyncResult:
    run_id: str
    usage: UpsertCounts
    cost: UpsertCounts
    watermarks: AnthropicWatermarks


@dataclass(frozen=True)
class AnthropicHistoryStatus:
    usage_last_complete_date: date | None
    cost_last_complete_date: date | None
    last_successful_sync_at: datetime | None


@dataclass(frozen=True)
class AnthropicHistoryRange:
    starting_at: date
    ending_at: date


class AnthropicHistoryRepository:
    """Persistence boundary for durable Anthropic provider facts."""

    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    def watermarks(self) -> AnthropicWatermarks:
        with self._session_factory() as session:
            return self._watermarks(session)

    def status(self) -> AnthropicHistoryStatus:
        with self._session_factory() as session:
            watermarks = self._watermarks(session)
            runs = session.scalars(
                select(AnthropicSyncRunORM)
                .where(AnthropicSyncRunORM.status == "succeeded")
                .order_by(AnthropicSyncRunORM.finished_at.desc())
                .limit(1)
            ).all()
            return AnthropicHistoryStatus(
                usage_last_complete_date=watermarks.usage,
                cost_last_complete_date=watermarks.cost,
                last_successful_sync_at=runs[0].finished_at if runs else None,
            )

    def history_range(self) -> AnthropicHistoryRange | None:
        """Return the inclusive bounds of the persisted, successfully synced history."""

        with self._session_factory() as session:
            usage_start, usage_end = session.execute(
                select(
                    func.min(AnthropicUsageDailyORM.bucket_date),
                    func.max(AnthropicUsageDailyORM.bucket_date),
                )
            ).one()
            cost_start, cost_end = session.execute(
                select(
                    func.min(AnthropicCostDailyORM.bucket_date),
                    func.max(AnthropicCostDailyORM.bucket_date),
                )
            ).one()
            sync_start = session.scalar(
                select(func.min(AnthropicSyncRunORM.completed_start_date)).where(
                    AnthropicSyncRunORM.status == "succeeded"
                )
            )
            watermarks = self._watermarks(session)

        starts = [value for value in (sync_start, usage_start, cost_start) if value is not None]
        ends = [
            value
            for value in (watermarks.usage, watermarks.cost, usage_end, cost_end)
            if value is not None
        ]
        if not starts or not ends:
            return None
        return AnthropicHistoryRange(starting_at=min(starts), ending_at=max(ends))

    def load_report(self, starting_at: date, ending_at: date) -> AnthropicAdminReport:
        if ending_at < starting_at:
            raise ValueError("End date must be on or after start date.")
        with self._session_factory() as session:
            usage_rows = session.scalars(
                select(AnthropicUsageDailyORM)
                .where(
                    AnthropicUsageDailyORM.bucket_date >= starting_at,
                    AnthropicUsageDailyORM.bucket_date <= ending_at,
                )
                .order_by(AnthropicUsageDailyORM.bucket_date, AnthropicUsageDailyORM.id)
            ).all()
            cost_rows = session.scalars(
                select(AnthropicCostDailyORM)
                .where(
                    AnthropicCostDailyORM.bucket_date >= starting_at,
                    AnthropicCostDailyORM.bucket_date <= ending_at,
                )
                .order_by(AnthropicCostDailyORM.bucket_date, AnthropicCostDailyORM.id)
            ).all()
            api_keys = session.scalars(select(AnthropicAPIKeyORM).order_by(AnthropicAPIKeyORM.name)).all()
            workspaces = session.scalars(select(AnthropicWorkspaceORM).order_by(AnthropicWorkspaceORM.name)).all()
            return AnthropicAdminReport(
                usage_rows=(),
                messages_usage_rows=tuple(_usage_domain(row) for row in usage_rows),
                cost_rows=tuple(_cost_domain(row) for row in cost_rows),
                api_keys=tuple(_api_key_domain(row) for row in api_keys),
                workspaces=tuple(_workspace_domain(row) for row in workspaces),
            )

    def persist_sync(
        self,
        report: AnthropicAdminReport,
        *,
        starting_at: date,
        ending_at: date,
        mode: str,
        started_at: datetime,
    ) -> PersistedSyncResult:
        """Atomically mirror a refreshed range and advance successful watermarks."""

        now = datetime.now(UTC)
        run_id = str(uuid4())
        with self._session_factory() as session:
            with session.begin():
                previous = self._watermarks(session, for_update=True)
                usage_counts = self._upsert_usage(session, report.messages_usage_rows, starting_at, ending_at, now)
                cost_counts = self._upsert_costs(session, report.cost_rows, starting_at, ending_at, now)
                self._upsert_metadata(session, report.api_keys, report.workspaces, now)
                session.flush()
                session.expire_all()
                self._reconcile_stored_range(session, report, starting_at, ending_at)

                resulting = AnthropicWatermarks(
                    usage=_next_watermark(previous.usage, starting_at, ending_at, mode),
                    cost=_next_watermark(previous.cost, starting_at, ending_at, mode),
                )
                self._set_watermark(session, USAGE_DATASET, resulting.usage, now)
                self._set_watermark(session, COST_DATASET, resulting.cost, now)
                session.add(
                    AnthropicSyncRunORM(
                        id=run_id,
                        mode=mode,
                        status="succeeded",
                        requested_start_date=starting_at,
                        requested_end_date=ending_at,
                        completed_start_date=starting_at,
                        completed_end_date=ending_at,
                        started_at=started_at,
                        finished_at=now,
                        usage_rows_fetched=len(report.messages_usage_rows),
                        usage_rows_inserted=usage_counts.inserted,
                        usage_rows_updated=usage_counts.updated,
                        cost_rows_fetched=len(report.cost_rows),
                        cost_rows_inserted=cost_counts.inserted,
                        cost_rows_updated=cost_counts.updated,
                        previous_usage_watermark=previous.usage,
                        resulting_usage_watermark=resulting.usage,
                        previous_cost_watermark=previous.cost,
                        resulting_cost_watermark=resulting.cost,
                        total_usage_tokens=report.total_api_tokens,
                        total_billed_cost=report.billed_organization_cost_usd,
                        currency=USD,
                    )
                )
        return PersistedSyncResult(run_id, usage_counts, cost_counts, resulting)

    def record_failure(
        self,
        *,
        starting_at: date,
        ending_at: date,
        mode: str,
        started_at: datetime,
        error_message: str,
    ) -> str:
        """Record a sanitized failure after the fact transaction has rolled back."""

        now = datetime.now(UTC)
        run_id = str(uuid4())
        safe_error = error_message[:1000]
        with self._session_factory() as session:
            with session.begin():
                watermarks = self._watermarks(session)
                session.add(
                    AnthropicSyncRunORM(
                        id=run_id,
                        mode=mode,
                        status="failed",
                        requested_start_date=starting_at,
                        requested_end_date=ending_at,
                        started_at=started_at,
                        finished_at=now,
                        previous_usage_watermark=watermarks.usage,
                        resulting_usage_watermark=watermarks.usage,
                        previous_cost_watermark=watermarks.cost,
                        resulting_cost_watermark=watermarks.cost,
                        total_usage_tokens=0,
                        total_billed_cost=Decimal("0"),
                        currency=USD,
                        error_message=safe_error,
                    )
                )
        return run_id

    def _upsert_usage(
        self,
        session: Session,
        rows: Sequence[MessagesUsageRow],
        starting_at: date,
        ending_at: date,
        now: datetime,
    ) -> UpsertCounts:
        existing_rows = session.scalars(
            select(AnthropicUsageDailyORM).where(
                AnthropicUsageDailyORM.bucket_date >= starting_at,
                AnthropicUsageDailyORM.bucket_date <= ending_at,
            )
        ).all()
        existing = {_usage_orm_identity(row): row for row in existing_rows}
        incoming = {_usage_identity(row): _usage_values(row, now) for row in rows}
        for identity, row in existing.items():
            if identity not in incoming:
                session.delete(row)
        _execute_upsert(
            session,
            AnthropicUsageDailyORM,
            list(incoming.values()),
            ["bucket_date", "api_key_id", "workspace_id", "model", "service_tier"],
            [
                "uncached_input_tokens",
                "cache_creation_1h_tokens",
                "cache_creation_5m_tokens",
                "cache_read_tokens",
                "output_tokens",
                "web_search_requests",
                "updated_at",
            ],
        )
        updated = len(set(existing) & set(incoming))
        return UpsertCounts(inserted=len(incoming) - updated, updated=updated)

    def _upsert_costs(
        self,
        session: Session,
        rows: Sequence[AnthropicCostRow],
        starting_at: date,
        ending_at: date,
        now: datetime,
    ) -> UpsertCounts:
        existing_rows = session.scalars(
            select(AnthropicCostDailyORM).where(
                AnthropicCostDailyORM.bucket_date >= starting_at,
                AnthropicCostDailyORM.bucket_date <= ending_at,
            )
        ).all()
        existing = {_cost_orm_identity(row): row for row in existing_rows}
        incoming = {_cost_identity(row): _cost_values(row, now) for row in rows}
        for identity, row in existing.items():
            if identity not in incoming:
                session.delete(row)
        _execute_upsert(
            session,
            AnthropicCostDailyORM,
            list(incoming.values()),
            ["bucket_date", "workspace_id", "description", "model", "cost_type", "token_type", "currency"],
            ["amount", "updated_at"],
        )
        updated = len(set(existing) & set(incoming))
        return UpsertCounts(inserted=len(incoming) - updated, updated=updated)

    @staticmethod
    def _upsert_metadata(
        session: Session,
        api_keys: Sequence[AnthropicAPIKeyMetadata],
        workspaces: Sequence[AnthropicWorkspaceMetadata],
        now: datetime,
    ) -> None:
        _execute_upsert(
            session,
            AnthropicAPIKeyORM,
            [
                {
                    "api_key_id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "workspace_id": row.workspace_id,
                    "partial_key_hint": row.partial_key_hint,
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
                for row in api_keys
            ],
            ["api_key_id"],
            ["name", "status", "workspace_id", "partial_key_hint", "last_seen_at"],
        )
        _execute_upsert(
            session,
            AnthropicWorkspaceORM,
            [
                {"workspace_id": row.id, "name": row.name, "first_seen_at": now, "last_seen_at": now}
                for row in workspaces
            ],
            ["workspace_id"],
            ["name", "last_seen_at"],
        )

    @staticmethod
    def _reconcile_stored_range(
        session: Session,
        report: AnthropicAdminReport,
        starting_at: date,
        ending_at: date,
    ) -> None:
        stored_usage = session.scalars(
            select(AnthropicUsageDailyORM).where(
                AnthropicUsageDailyORM.bucket_date >= starting_at,
                AnthropicUsageDailyORM.bucket_date <= ending_at,
            )
        ).all()
        stored_costs = session.scalars(
            select(AnthropicCostDailyORM).where(
                AnthropicCostDailyORM.bucket_date >= starting_at,
                AnthropicCostDailyORM.bucket_date <= ending_at,
            )
        ).all()
        if len(stored_usage) != len(report.messages_usage_rows) or len(stored_costs) != len(report.cost_rows):
            raise RuntimeError("Persisted Anthropic row counts did not reconcile with the provider response.")
        stored_tokens = sum(_usage_domain(row).total_tokens for row in stored_usage)
        stored_cost = sum((row.amount for row in stored_costs), Decimal("0"))
        if stored_tokens != report.total_api_tokens or stored_cost != report.billed_organization_cost_usd:
            raise RuntimeError("Persisted Anthropic totals did not reconcile with the provider response.")

    @staticmethod
    def _watermarks(session: Session, *, for_update: bool = False) -> AnthropicWatermarks:
        statement = select(AnthropicSyncWatermarkORM)
        if for_update:
            statement = statement.with_for_update()
        rows = {row.dataset: row for row in session.scalars(statement).all()}
        return AnthropicWatermarks(
            usage=rows.get(USAGE_DATASET).last_complete_date if rows.get(USAGE_DATASET) else None,
            cost=rows.get(COST_DATASET).last_complete_date if rows.get(COST_DATASET) else None,
        )

    @staticmethod
    def _set_watermark(session: Session, dataset: str, value: date | None, now: datetime) -> None:
        row = session.get(AnthropicSyncWatermarkORM, dataset)
        if row is None:
            session.add(
                AnthropicSyncWatermarkORM(
                    dataset=dataset,
                    last_complete_date=value,
                    last_successful_sync_at=now,
                    updated_at=now,
                )
            )
            return
        row.last_complete_date = value
        row.last_successful_sync_at = now
        row.updated_at = now


def _execute_upsert(
    session: Session,
    model: type[Any],
    values: list[dict[str, Any]],
    identity_columns: list[str],
    update_columns: list[str],
) -> None:
    if not values:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(model).values(values)
    elif dialect == "sqlite":
        statement = sqlite_insert(model).values(values)
    else:
        raise RuntimeError(f"Anthropic history UPSERT is not supported for database dialect '{dialect}'.")
    statement = statement.on_conflict_do_update(
        index_elements=identity_columns,
        set_={column: getattr(statement.excluded, column) for column in update_columns},
    )
    session.execute(statement)


def _next_watermark(previous: date | None, starting_at: date, ending_at: date, mode: str) -> date | None:
    if previous is None:
        return ending_at if mode == "bootstrap" else None
    if starting_at <= previous + timedelta(days=1):
        return max(previous, ending_at)
    return previous


def _usage_identity(row: MessagesUsageRow) -> UsageIdentity:
    return (date.fromisoformat(row.date), row.api_key_id, row.workspace_id, row.model, row.service_tier)


def _usage_orm_identity(row: AnthropicUsageDailyORM) -> UsageIdentity:
    return (row.bucket_date, row.api_key_id, row.workspace_id, row.model, row.service_tier)


def _cost_identity(row: AnthropicCostRow) -> CostIdentity:
    return (
        date.fromisoformat(row.date),
        row.workspace_id,
        row.description,
        row.model,
        row.cost_type,
        row.token_type,
        USD,
    )


def _cost_orm_identity(row: AnthropicCostDailyORM) -> CostIdentity:
    return (
        row.bucket_date,
        row.workspace_id,
        row.description,
        row.model,
        row.cost_type,
        row.token_type,
        row.currency,
    )


def _usage_values(row: MessagesUsageRow, now: datetime) -> dict[str, Any]:
    return {
        "bucket_date": date.fromisoformat(row.date),
        "api_key_id": row.api_key_id,
        "workspace_id": row.workspace_id,
        "model": row.model,
        "service_tier": row.service_tier,
        "uncached_input_tokens": row.uncached_input_tokens,
        "cache_creation_1h_tokens": row.cache_creation_1h_tokens,
        "cache_creation_5m_tokens": row.cache_creation_5m_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "output_tokens": row.output_tokens,
        "web_search_requests": row.web_search_requests,
        "created_at": now,
        "updated_at": now,
    }


def _cost_values(row: AnthropicCostRow, now: datetime) -> dict[str, Any]:
    return {
        "bucket_date": date.fromisoformat(row.date),
        "workspace_id": row.workspace_id,
        "description": row.description,
        "model": row.model,
        "cost_type": row.cost_type,
        "token_type": row.token_type,
        "amount": row.amount_usd,
        "currency": USD,
        "created_at": now,
        "updated_at": now,
    }


def _usage_domain(row: AnthropicUsageDailyORM) -> MessagesUsageRow:
    return MessagesUsageRow(
        date=row.bucket_date.isoformat(),
        api_key_id=row.api_key_id,
        workspace_id=row.workspace_id,
        model=row.model,
        service_tier=row.service_tier,
        uncached_input_tokens=row.uncached_input_tokens,
        cache_creation_1h_tokens=row.cache_creation_1h_tokens,
        cache_creation_5m_tokens=row.cache_creation_5m_tokens,
        cache_read_tokens=row.cache_read_tokens,
        output_tokens=row.output_tokens,
        web_search_requests=row.web_search_requests,
    )


def _cost_domain(row: AnthropicCostDailyORM) -> AnthropicCostRow:
    return AnthropicCostRow(
        date=row.bucket_date.isoformat(),
        workspace_id=row.workspace_id,
        description=row.description,
        model=row.model,
        cost_type=row.cost_type,
        token_type=row.token_type,
        amount_usd=row.amount,
    )


def _api_key_domain(row: AnthropicAPIKeyORM) -> AnthropicAPIKeyMetadata:
    return AnthropicAPIKeyMetadata(
        id=row.api_key_id,
        name=row.name,
        status=row.status,
        workspace_id=row.workspace_id,
        partial_key_hint=row.partial_key_hint,
    )


def _workspace_domain(row: AnthropicWorkspaceORM) -> AnthropicWorkspaceMetadata:
    return AnthropicWorkspaceMetadata(id=row.workspace_id, name=row.name)
