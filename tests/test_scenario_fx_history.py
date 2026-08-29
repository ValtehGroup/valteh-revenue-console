from datetime import UTC, date, datetime
from decimal import Decimal

from dash import Dash, no_update
from dash.development.base_component import Component

from app.domain.fx_rates import FxRateObservation, FxRateStatus, FxRateUpsertResult
from app.pages.scenarios import (
    _fx_history_figure,
    _fx_history_panel,
    _latest_reference_rate,
    _update_fx_history,
    register_callbacks,
)
from app.utils.currency import STATIC_EXCHANGE_RATES_TO_MXN


class FakeFxRepository:
    def __init__(self, observations=()) -> None:
        self.rows = list(observations)
        self.upsert_calls = []

    def status(self) -> FxRateStatus:
        latest = max(self.rows, key=lambda row: row.rate_date) if self.rows else None
        return FxRateStatus(latest, datetime(2026, 8, 29, tzinfo=UTC) if latest else None)

    def latest(self) -> FxRateObservation | None:
        return self.status().latest

    def observations(self, starting_at: date, ending_at: date):
        return sorted(
            (row for row in self.rows if starting_at <= row.rate_date <= ending_at),
            key=lambda row: row.rate_date,
        )

    def upsert(self, observations):
        incoming = list(observations)
        self.upsert_calls.append(incoming)
        existing = {(row.series_id, row.rate_date): row for row in self.rows}
        inserted = 0
        updated = 0
        for row in incoming:
            key = (row.series_id, row.rate_date)
            if key in existing:
                updated += 1
            else:
                inserted += 1
            existing[key] = row
        self.rows = list(existing.values())
        return FxRateUpsertResult(inserted, updated)


class FakeFxClient:
    def __init__(self, observations=(), error: Exception | None = None) -> None:
        self.observations = tuple(observations)
        self.error = error
        self.calls = []

    def fetch_usd_mxn_fix(self, starting_at: date, ending_at: date):
        self.calls.append((starting_at, ending_at))
        if self.error is not None:
            raise self.error
        return self.observations


def _observation(day: date, rate: str) -> FxRateObservation:
    return FxRateObservation("SF43718", day, Decimal(rate))


def test_fx_panel_reads_persisted_history_without_calling_provider() -> None:
    repository = FakeFxRepository([_observation(date(2026, 8, 28), "17.2500")])

    panel = _fx_history_panel(repository)

    assert "Latest FIX 17.2500" in str(panel)
    assert repository.upsert_calls == []
    assert _find_component(panel, "scenario-fx-update") is not None
    assert _find_component(panel, "scenario-fx-history-chart") is not None


def test_latest_persisted_fix_is_the_scenario_reference_rate() -> None:
    repository = FakeFxRepository(
        [
            _observation(date(2026, 8, 27), "17.1000"),
            _observation(date(2026, 8, 28), "17.2500"),
        ]
    )

    assert _latest_reference_rate(repository) == Decimal("17.2500")


def test_fx_sync_callback_runs_only_from_explicit_button_click() -> None:
    app = Dash(__name__, suppress_callback_exceptions=True)

    register_callbacks(app)

    callback = next(item for item in app._callback_list if "scenario-fx-history-chart.figure" in item["output"])
    assert callback["prevent_initial_call"] is True
    assert callback["inputs"] == [{"id": "scenario-fx-update", "property": "n_clicks"}]


def test_successful_fx_update_sets_baseline_and_refreshes_persisted_chart() -> None:
    repository = FakeFxRepository()
    latest = _observation(date(2026, 8, 28), "17.2500")
    client = FakeFxClient([latest])

    baseline, status, latest_label, figure = _update_fx_history(repository, client)

    assert baseline == "17.2500"
    assert "1 inserted" in str(status)
    assert latest_label == "Latest FIX 17.2500 · 2026-08-28"
    assert list(figure.data[0].y) == [17.25]
    assert repository.latest() == latest
    assert len(client.calls) == 1


def test_failed_fx_update_preserves_baseline_chart_and_persisted_history() -> None:
    existing = _observation(date(2026, 8, 27), "17.1000")
    repository = FakeFxRepository([existing])
    client = FakeFxClient(error=RuntimeError("provider unavailable"))

    baseline, status, latest_label, figure = _update_fx_history(repository, client)

    assert baseline is no_update
    assert latest_label is no_update
    assert figure is no_update
    assert "provider unavailable" in str(status)
    assert repository.latest() == existing
    assert repository.upsert_calls == []


def test_fx_chart_shows_only_supplied_persisted_observations() -> None:
    observations = [
        _observation(date(2026, 8, 27), "17.1000"),
        _observation(date(2026, 8, 28), "17.2500"),
    ]

    figure = _fx_history_figure(observations)

    assert list(figure.data[0].x) == [date(2026, 8, 27), date(2026, 8, 28)]
    assert list(figure.data[0].y) == [17.1, 17.25]


def test_fx_history_does_not_change_static_cost_ingestion_rate() -> None:
    assert STATIC_EXCHANGE_RATES_TO_MXN["USD"] == Decimal("18")


def _find_component(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component
    if not isinstance(component, Component):
        return None
    children = getattr(component, "children", None)
    if children is None:
        return None
    for child in children if isinstance(children, (list, tuple)) else [children]:
        match = _find_component(child, component_id)
        if match is not None:
            return match
    return None
