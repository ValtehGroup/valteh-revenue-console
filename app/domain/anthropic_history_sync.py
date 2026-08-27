from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.data.anthropic_history_repository import (
    AnthropicHistoryRepository,
    AnthropicWatermarks,
    PersistedSyncResult,
)
from app.domain.anthropic_cost_allocation import allocate_anthropic_costs
from app.integrations.anthropic_admin_api import AnthropicAdminReport

BOOTSTRAP_START_DATE = date(2026, 7, 1)
DEFAULT_OVERLAP_DAYS = 7
MAX_SYNC_WINDOW_DAYS = 31
ALLOCATION_TOLERANCE_USD = Decimal("0.000000001")
SYNC_MODES = {"bootstrap", "incremental", "repair"}


class HistoricalAnthropicClient(Protocol):
    def fetch_historical_report(self, starting_at: date, ending_at: date) -> AnthropicAdminReport: ...


@dataclass(frozen=True)
class AnthropicSyncRequest:
    mode: str = "incremental"
    start_date: date | None = None
    end_date: date | None = None
    month: str | None = None
    overlap_days: int = DEFAULT_OVERLAP_DAYS
    dry_run: bool = False


@dataclass(frozen=True)
class AnthropicSyncResult:
    mode: str
    starting_at: date
    ending_at: date
    windows: tuple[tuple[date, date], ...]
    report: AnthropicAdminReport
    persisted: PersistedSyncResult | None

    @property
    def dry_run(self) -> bool:
        return self.persisted is None


class AnthropicHistorySyncService:
    """Coordinates explicit history syncs from operations or a user action."""

    def __init__(
        self,
        client: HistoricalAnthropicClient,
        repository: AnthropicHistoryRepository,
        *,
        utc_today: Callable[[], date] | None = None,
    ) -> None:
        self._client = client
        self._repository = repository
        self._utc_today = utc_today or (lambda: datetime.now(UTC).date())

    def sync(self, request: AnthropicSyncRequest) -> AnthropicSyncResult:
        starting_at, ending_at = resolve_sync_range(request, self._repository.watermarks(), self._utc_today())
        windows = tuple(split_date_range(starting_at, ending_at))
        started_at = datetime.now(UTC)
        try:
            report = _merge_reports(
                self._client.fetch_historical_report(window_start, window_end) for window_start, window_end in windows
            )
            _validate_provider_report(report, starting_at, ending_at)
            allocation = allocate_anthropic_costs(report.messages_usage_rows, report.cost_rows)
            if (
                abs(
                    allocation.allocated_cost_usd
                    + allocation.unallocated_cost_usd
                    - report.billed_organization_cost_usd
                )
                > ALLOCATION_TOLERANCE_USD
            ):
                raise RuntimeError("Anthropic allocation did not reconcile to billed provider cost.")
            if request.dry_run:
                return AnthropicSyncResult(request.mode, starting_at, ending_at, windows, report, None)
            persisted = self._repository.persist_sync(
                report,
                starting_at=starting_at,
                ending_at=ending_at,
                mode=request.mode,
                started_at=started_at,
            )
            return AnthropicSyncResult(request.mode, starting_at, ending_at, windows, report, persisted)
        except Exception as exc:
            if not request.dry_run:
                try:
                    self._repository.record_failure(
                        starting_at=starting_at,
                        ending_at=ending_at,
                        mode=request.mode,
                        started_at=started_at,
                        error_message=safe_sync_error_message(exc),
                    )
                except Exception:
                    pass
            raise


def resolve_sync_range(
    request: AnthropicSyncRequest,
    watermarks: AnthropicWatermarks,
    utc_today: date,
) -> tuple[date, date]:
    if request.mode not in SYNC_MODES:
        raise ValueError("Mode must be bootstrap, incremental, or repair.")
    if request.overlap_days < 0:
        raise ValueError("Overlap days cannot be negative.")
    if request.month and (request.start_date or request.end_date):
        raise ValueError("Use either --month or an explicit start/end range, not both.")
    if (request.start_date is None) != (request.end_date is None):
        raise ValueError("Start date and end date must be provided together.")

    latest_complete_date = utc_today - timedelta(days=1)
    if request.month:
        starting_at, ending_at = _month_range(request.month)
        ending_at = min(ending_at, latest_complete_date)
    elif request.start_date and request.end_date:
        starting_at, ending_at = request.start_date, request.end_date
    elif request.mode == "bootstrap":
        starting_at, ending_at = BOOTSTRAP_START_DATE, latest_complete_date
    elif request.mode == "repair":
        raise ValueError("Repair mode requires --month or an explicit start/end range.")
    else:
        known = [value for value in (watermarks.usage, watermarks.cost) if value is not None]
        if len(known) != 2:
            raise ValueError("Historical watermarks are not initialized. Run the July 2026 bootstrap first.")
        earliest = min(known)
        starting_at = max(
            BOOTSTRAP_START_DATE,
            earliest + timedelta(days=1 - request.overlap_days),
        )
        ending_at = latest_complete_date

    if ending_at < starting_at:
        raise ValueError("The requested synchronization range has no complete UTC days.")
    if ending_at >= utc_today:
        raise ValueError("The current UTC day is incomplete and cannot be persisted.")
    return starting_at, ending_at


def split_date_range(starting_at: date, ending_at: date) -> Iterable[tuple[date, date]]:
    cursor = starting_at
    while cursor <= ending_at:
        window_end = min(cursor + timedelta(days=MAX_SYNC_WINDOW_DAYS - 1), ending_at)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _month_range(value: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValueError("Month must use YYYY-MM format.") from exc
    next_month = date(first.year + (first.month == 12), 1 if first.month == 12 else first.month + 1, 1)
    return first, next_month - timedelta(days=1)


def _merge_reports(reports: Iterable[AnthropicAdminReport]) -> AnthropicAdminReport:
    usage_rows = []
    cost_rows = []
    api_keys = {}
    workspaces = {}
    for report in reports:
        usage_rows.extend(report.messages_usage_rows)
        cost_rows.extend(report.cost_rows)
        api_keys.update({row.id: row for row in report.api_keys})
        workspaces.update({row.id: row for row in report.workspaces})
    return AnthropicAdminReport(
        usage_rows=(),
        messages_usage_rows=tuple(usage_rows),
        cost_rows=tuple(cost_rows),
        api_keys=tuple(api_keys.values()),
        workspaces=tuple(workspaces.values()),
    )


def _validate_provider_report(report: AnthropicAdminReport, starting_at: date, ending_at: date) -> None:
    usage_identities = [
        (row.date, row.api_key_id, row.workspace_id, row.model, row.service_tier) for row in report.messages_usage_rows
    ]
    cost_identities = [
        (row.date, row.workspace_id, row.description, row.model, row.cost_type, row.token_type)
        for row in report.cost_rows
    ]
    if len(usage_identities) != len(set(usage_identities)):
        raise RuntimeError("Anthropic returned duplicate daily usage identities.")
    if len(cost_identities) != len(set(cost_identities)):
        raise RuntimeError("Anthropic returned duplicate daily cost identities.")
    for raw_date in [row.date for row in report.messages_usage_rows] + [row.date for row in report.cost_rows]:
        try:
            row_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise RuntimeError("Anthropic returned a fact with an invalid UTC date.") from exc
        if not starting_at <= row_date <= ending_at:
            raise RuntimeError("Anthropic returned a fact outside the requested UTC range.")


def safe_sync_error_message(exc: Exception) -> str:
    if isinstance(exc, (ValueError, RuntimeError)):
        message = str(exc)
    else:
        message = "Anthropic history synchronization failed."
    message = re.sub(r"sk-ant-[^\s,;]+", "[REDACTED]", message, flags=re.IGNORECASE)
    message = re.sub(r"apikey_[A-Za-z0-9]+", "[API_KEY_ID_REDACTED]", message)
    return message[:1000]
