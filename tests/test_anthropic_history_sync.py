from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data.anthropic_history_repository import (
    AnthropicHistoryRange,
    AnthropicHistoryRepository,
    AnthropicHistoryStatus,
    AnthropicWatermarks,
)
from app.data.schemas import (
    AnthropicCostDailyORM,
    AnthropicSyncRunORM,
    AnthropicUsageDailyORM,
    Base,
)
from app.domain.anthropic_history_sync import (
    AnthropicHistorySyncService,
    AnthropicSyncRequest,
    resolve_sync_range,
    safe_sync_error_message,
    split_date_range,
)
from app.integrations.anthropic_admin_api import AnthropicAdminReport, AnthropicCostRow, MessagesUsageRow
from app.pages.usage import (
    _historical_report_content,
    _is_cached_live_report,
    _render_serialized_report,
    _report_content,
    _report_content_with_data,
    _update_historical_report,
)


class FakeHistoryClient:
    def __init__(self, reports: list[AnthropicAdminReport]) -> None:
        self.reports = reports
        self.calls: list[tuple[date, date]] = []

    def fetch_historical_report(self, starting_at: date, ending_at: date) -> AnthropicAdminReport:
        self.calls.append((starting_at, ending_at))
        return self.reports.pop(0)


def _repository() -> tuple[AnthropicHistoryRepository, sessionmaker]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return AnthropicHistoryRepository(factory), factory


def _report(day: date, *, tokens: int = 100, cost: str = "1.25") -> AnthropicAdminReport:
    return AnthropicAdminReport(
        usage_rows=(),
        messages_usage_rows=(
            MessagesUsageRow(
                date=day.isoformat(),
                api_key_id="apikey_123",
                workspace_id="workspace_123",
                model="claude-sonnet",
                service_tier="standard",
                uncached_input_tokens=tokens,
                cache_creation_1h_tokens=0,
                cache_creation_5m_tokens=0,
                cache_read_tokens=0,
                output_tokens=0,
                web_search_requests=0,
            ),
        ),
        cost_rows=(
            AnthropicCostRow(
                date=day.isoformat(),
                workspace_id="workspace_123",
                description="Claude usage",
                model="claude-sonnet",
                cost_type="tokens",
                token_type="uncached_input_tokens",
                amount_usd=Decimal(cost),
            ),
        ),
    )


def _merge(*reports: AnthropicAdminReport) -> AnthropicAdminReport:
    return AnthropicAdminReport(
        usage_rows=(),
        messages_usage_rows=tuple(row for report in reports for row in report.messages_usage_rows),
        cost_rows=tuple(row for report in reports for row in report.cost_rows),
    )


def test_rerun_and_overlap_replace_values_without_duplicates() -> None:
    repository, factory = _repository()
    started_at = datetime.now(UTC)
    july_1 = date(2026, 7, 1)
    july_2 = date(2026, 7, 2)
    july_3 = date(2026, 7, 3)

    first = _merge(_report(july_1), _report(july_2))
    result = repository.persist_sync(
        first, starting_at=july_1, ending_at=july_2, mode="bootstrap", started_at=started_at
    )
    assert result.usage.inserted == 2
    assert result.watermarks == AnthropicWatermarks(july_2, july_2)

    refreshed = _merge(_report(july_2, tokens=225, cost="2.50"), _report(july_3))
    result = repository.persist_sync(
        refreshed, starting_at=july_2, ending_at=july_3, mode="incremental", started_at=started_at
    )
    assert result.usage == result.cost
    assert result.usage.inserted == 1
    assert result.usage.updated == 1
    assert result.watermarks == AnthropicWatermarks(july_3, july_3)

    repository.persist_sync(refreshed, starting_at=july_2, ending_at=july_3, mode="repair", started_at=started_at)
    old_repair = _report(july_1, tokens=150, cost="1.50")
    repair_result = repository.persist_sync(
        old_repair,
        starting_at=july_1,
        ending_at=july_1,
        mode="repair",
        started_at=started_at,
    )
    assert repair_result.watermarks == AnthropicWatermarks(july_3, july_3)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AnthropicUsageDailyORM)) == 3
        assert session.scalar(select(func.count()).select_from(AnthropicCostDailyORM)) == 3
        july_2_usage = session.scalar(
            select(AnthropicUsageDailyORM).where(AnthropicUsageDailyORM.bucket_date == july_2)
        )
        july_2_cost = session.scalar(select(AnthropicCostDailyORM).where(AnthropicCostDailyORM.bucket_date == july_2))
        assert july_2_usage.uncached_input_tokens == 225
        assert july_2_cost.amount == Decimal("2.500000000000")


def test_history_range_spans_all_persisted_usage_and_cost_facts() -> None:
    repository, _factory = _repository()
    repository.persist_sync(
        _merge(_report(date(2026, 7, 3)), _report(date(2026, 8, 4))),
        starting_at=date(2026, 7, 1),
        ending_at=date(2026, 8, 4),
        mode="bootstrap",
        started_at=datetime.now(UTC),
    )

    assert repository.history_range() == AnthropicHistoryRange(date(2026, 7, 1), date(2026, 8, 4))


def test_failed_persistence_rolls_back_facts_and_does_not_advance_watermarks(monkeypatch) -> None:
    repository, factory = _repository()
    client = FakeHistoryClient([_report(date(2026, 7, 1))])

    def fail_reconciliation(*_args):
        raise RuntimeError("Forced reconciliation failure.")

    monkeypatch.setattr(repository, "_reconcile_stored_range", fail_reconciliation)
    service = AnthropicHistorySyncService(client, repository, utc_today=lambda: date(2026, 7, 3))

    with pytest.raises(RuntimeError, match="Forced reconciliation"):
        service.sync(AnthropicSyncRequest(mode="bootstrap", end_date=date(2026, 7, 1), start_date=date(2026, 7, 1)))

    assert repository.watermarks() == AnthropicWatermarks()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AnthropicUsageDailyORM)) == 0
        run = session.scalar(select(AnthropicSyncRunORM))
        assert run.status == "failed"
        assert run.resulting_usage_watermark is None


def test_dry_run_and_date_segmentation_make_no_database_writes() -> None:
    repository, factory = _repository()
    empty = AnthropicAdminReport(usage_rows=(), messages_usage_rows=(), cost_rows=())
    client = FakeHistoryClient([empty, empty])
    service = AnthropicHistorySyncService(client, repository, utc_today=lambda: date(2026, 8, 2))

    result = service.sync(AnthropicSyncRequest(mode="bootstrap", dry_run=True))

    assert result.starting_at == date(2026, 7, 1)
    assert result.ending_at == date(2026, 8, 1)
    assert client.calls == [(date(2026, 7, 1), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 8, 1))]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AnthropicSyncRunORM)) == 0


def test_incremental_range_uses_independent_watermarks_and_overlap() -> None:
    request = AnthropicSyncRequest(overlap_days=7)
    resolved = resolve_sync_range(
        request,
        AnthropicWatermarks(usage=date(2026, 8, 31), cost=date(2026, 8, 28)),
        date(2026, 9, 5),
    )

    assert resolved == (date(2026, 8, 22), date(2026, 9, 4))
    assert list(split_date_range(date(2026, 7, 1), date(2026, 8, 1))) == [
        (date(2026, 7, 1), date(2026, 7, 31)),
        (date(2026, 8, 1), date(2026, 8, 1)),
    ]


def test_current_utc_day_and_uninitialized_incremental_sync_are_rejected() -> None:
    with pytest.raises(ValueError, match="current UTC day"):
        resolve_sync_range(
            AnthropicSyncRequest(
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 27),
            ),
            AnthropicWatermarks(date(2026, 8, 1), date(2026, 8, 1)),
            date(2026, 8, 27),
        )
    with pytest.raises(ValueError, match="bootstrap"):
        resolve_sync_range(AnthropicSyncRequest(), AnthropicWatermarks(), date(2026, 8, 27))


def test_historical_dashboard_read_does_not_call_api_or_sync() -> None:
    class ReadOnlyHistory:
        def __init__(self) -> None:
            self.calls = []

        def load_report(self, starting_at, ending_at):
            self.calls.append((starting_at, ending_at))
            return AnthropicAdminReport(usage_rows=(), messages_usage_rows=(), cost_rows=())

    class ForbiddenLiveClient:
        def fetch_report(self, *_args):
            pytest.fail("Historical dashboard reads must not call Anthropic")

    history = ReadOnlyHistory()
    component = _report_content(
        "historical",
        "2026-07-01",
        "2026-08-01",
        client=ForbiddenLiveClient(),
        history_repository=history,
    )

    assert history.calls == [(date(2026, 7, 1), date(2026, 8, 1))]
    assert "Historical database report" in str(component)


def test_historical_report_automatically_loads_the_complete_persisted_range() -> None:
    class ReadOnlyHistory:
        def __init__(self) -> None:
            self.calls = []

        def history_range(self):
            return AnthropicHistoryRange(date(2026, 7, 1), date(2026, 8, 26))

        def load_report(self, starting_at, ending_at):
            self.calls.append((starting_at, ending_at))
            return AnthropicAdminReport(usage_rows=(), messages_usage_rows=(), cost_rows=())

    history = ReadOnlyHistory()
    component = _historical_report_content(history)

    assert history.calls == [(date(2026, 7, 1), date(2026, 8, 26))]
    assert "2026-07-01 through 2026-08-26" in str(component)


def test_history_update_uses_incremental_sync_then_reloads_all_history() -> None:
    report = _report(date(2026, 8, 26))

    class History:
        def __init__(self) -> None:
            self.calls = []

        def watermarks(self):
            return AnthropicWatermarks(date(2026, 8, 25), date(2026, 8, 25))

        def history_range(self):
            return AnthropicHistoryRange(date(2026, 7, 1), date(2026, 8, 26))

        def load_report(self, starting_at, ending_at):
            self.calls.append((starting_at, ending_at))
            return report

        def status(self):
            return AnthropicHistoryStatus(
                usage_last_complete_date=date(2026, 8, 26),
                cost_last_complete_date=date(2026, 8, 26),
                last_successful_sync_at=datetime(2026, 8, 27, tzinfo=UTC),
            )

    class SyncService:
        def __init__(self) -> None:
            self.requests = []

        def sync(self, request):
            self.requests.append(request)
            return type(
                "Result",
                (),
                {
                    "starting_at": date(2026, 8, 19),
                    "ending_at": date(2026, 8, 26),
                    "report": report,
                },
            )()

    history = History()
    service = SyncService()
    component, status_message, color = _update_historical_report(history, sync_service=service)

    assert service.requests == [AnthropicSyncRequest(mode="incremental")]
    assert history.calls == [(date(2026, 7, 1), date(2026, 8, 26))]
    assert "History updated for 2026-08-19 through 2026-08-26" in str(component)
    assert "usage through 2026-08-26" in status_message
    assert color == "success"


def test_live_dashboard_report_does_not_touch_history_repository() -> None:
    class LiveClient:
        def fetch_report(self, starting_at, ending_at):
            return _report(starting_at)

    class ForbiddenHistory:
        def load_report(self, *_args):
            pytest.fail("Live dashboard reports must not access historical persistence")

    component = _report_content(
        "live",
        "2026-07-01",
        "2026-07-01",
        client=LiveClient(),
        history_repository=ForbiddenHistory(),
    )

    assert "Live Admin API report" in str(component)


def test_live_report_data_can_be_cached_and_rendered_without_calling_api_again() -> None:
    class LiveClient:
        def __init__(self) -> None:
            self.calls = []

        def fetch_report(self, starting_at, ending_at):
            self.calls.append((starting_at, ending_at))
            return _report(starting_at)

    client = LiveClient()
    component, report_data = _report_content_with_data(
        "live",
        "2026-08-20",
        "2026-08-26",
        client=client,
    )

    assert client.calls == [(date(2026, 8, 20), date(2026, 8, 26))]
    assert report_data is not None
    assert _is_cached_live_report(report_data)
    assert "Live Admin API report" in str(component)
    assert "2026-08-20 through 2026-08-26" in str(_render_serialized_report(report_data))


def test_invalid_or_historical_report_data_is_not_used_as_live_cache() -> None:
    assert not _is_cached_live_report(None)
    assert not _is_cached_live_report({"source": "historical"})
    assert not _is_cached_live_report({"source": "live", "starting_at": "2026-08-20"})


def test_sync_errors_redact_secrets_and_api_key_ids() -> None:
    message = safe_sync_error_message(RuntimeError("sk-ant-admin-secret failed for apikey_abc123"))

    assert "sk-ant" not in message
    assert "apikey_abc123" not in message
    assert "[REDACTED]" in message
