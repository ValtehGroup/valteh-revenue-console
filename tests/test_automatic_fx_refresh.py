from datetime import date
from decimal import Decimal

from app.domain.fx_rates import FxRateObservation, FxRateUpsertResult
from app.integrations import automatic_fx_refresh
from app.integrations.banxico_sie_api import BanxicoSIEAPIError
from app.routes import _refresh_fx_history_if_needed, _stale_fx_warning


class FakeFxRepository:
    def __init__(self, observations: list[FxRateObservation]) -> None:
        self.observations = observations

    def latest(self) -> FxRateObservation | None:
        return max(self.observations, key=lambda row: row.rate_date) if self.observations else None

    def upsert(self, observations) -> FxRateUpsertResult:
        self.observations.extend(observations)
        return FxRateUpsertResult(inserted=len(observations), updated=0)


class FakeFxClient:
    def __init__(self, observations: list[FxRateObservation]) -> None:
        self.observations = observations

    def fetch_usd_mxn_fix(self, _starting_at: date, _ending_at: date):
        return self.observations


def _observation(day: date, rate: str) -> FxRateObservation:
    return FxRateObservation("SF43718", day, Decimal(rate))


def test_automatic_refresh_uses_conditional_sync() -> None:
    repository = FakeFxRepository([_observation(date(2026, 8, 20), "17.10")])
    client = FakeFxClient([_observation(date(2026, 8, 28), "17.25")])

    result = automatic_fx_refresh.refresh_stale_fx_history(
        repository=repository,
        client=client,
        mexico_today=lambda: date(2026, 8, 28),
    )

    assert result is not None
    assert result.latest.rate_date == date(2026, 8, 28)


def test_route_refresh_failure_is_safe_and_does_not_escape(monkeypatch) -> None:
    def fail_refresh() -> None:
        raise BanxicoSIEAPIError("Could not connect to the Banxico SIE API.")

    monkeypatch.setattr("app.routes.refresh_stale_fx_history", fail_refresh)

    assert _refresh_fx_history_if_needed() == "Could not connect to the Banxico SIE API."


def test_stale_warning_names_latest_fix_date_and_manual_retry() -> None:
    repository = FakeFxRepository([_observation(date(2026, 8, 20), "17.10")])

    warning = _stale_fx_warning(repository, mexico_today=lambda: date(2026, 8, 28))

    assert "2026-08-20" in str(warning)
    assert "Update FX history" in str(warning)


def test_fresh_fix_does_not_show_warning() -> None:
    repository = FakeFxRepository([_observation(date(2026, 8, 21), "17.10")])

    assert _stale_fx_warning(repository, mexico_today=lambda: date(2026, 8, 28)) is None
