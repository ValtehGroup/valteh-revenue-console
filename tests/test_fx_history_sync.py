from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data.fx_rate_repository import FxRateRepository
from app.data.schemas import Base, USDMXNRateORM
from app.domain.fx_history_sync import FX_HISTORY_START_DATE, FxHistorySyncService, resolve_fx_sync_range
from app.domain.fx_rates import FxRateObservation


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


def _repository() -> tuple[FxRateRepository, sessionmaker]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return FxRateRepository(factory), factory


def _observation(day: date, rate: str) -> FxRateObservation:
    return FxRateObservation("SF43718", day, Decimal(rate))


def test_repository_upsert_is_idempotent_and_refreshes_existing_rate() -> None:
    repository, factory = _repository()
    day = date(2026, 8, 28)

    first = repository.upsert([_observation(day, "17.1000")])
    refreshed = repository.upsert([_observation(day, "17.2500")])

    assert (first.inserted, first.updated) == (1, 0)
    assert (refreshed.inserted, refreshed.updated) == (0, 1)
    assert repository.latest() == _observation(day, "17.250000")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(USDMXNRateORM)) == 1


def test_repository_returns_chronological_range() -> None:
    repository, _factory = _repository()
    repository.upsert(
        [
            _observation(date(2026, 8, 28), "17.25"),
            _observation(date(2026, 8, 27), "17.10"),
        ]
    )

    rows = repository.observations(date(2026, 8, 27), date(2026, 8, 28))

    assert [row.rate_date for row in rows] == [date(2026, 8, 27), date(2026, 8, 28)]


def test_repository_rate_book_loads_prior_business_day_for_requested_range() -> None:
    repository, _factory = _repository()
    repository.upsert([_observation(date(2026, 5, 29), "18.25")])

    rate_book = repository.rate_book(date(2026, 5, 31), date(2026, 5, 31))

    resolved = rate_book.resolve("USD", date(2026, 5, 31))
    assert resolved.rate == Decimal("18.250000")
    assert resolved.observation_date == date(2026, 5, 29)


def test_sync_bootstraps_then_uses_seven_day_overlap() -> None:
    repository, _factory = _repository()
    latest_day = date(2026, 8, 28)
    client = FakeFxClient([_observation(latest_day, "17.25")])
    service = FxHistorySyncService(client, repository, mexico_today=lambda: latest_day)

    result = service.sync()

    assert client.calls == [(FX_HISTORY_START_DATE, latest_day)]
    assert result.latest.rate == Decimal("17.250000")
    assert resolve_fx_sync_range(result.latest, date(2026, 8, 29)) == (date(2026, 8, 21), date(2026, 8, 29))


def test_failed_fetch_leaves_existing_history_unchanged() -> None:
    repository, factory = _repository()
    existing = _observation(date(2026, 8, 28), "17.25")
    repository.upsert([existing])
    service = FxHistorySyncService(
        FakeFxClient(error=RuntimeError("provider unavailable")),
        repository,
        mexico_today=lambda: date(2026, 8, 29),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.sync()

    assert repository.latest() == _observation(date(2026, 8, 28), "17.250000")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(USDMXNRateORM)) == 1


def test_empty_bootstrap_does_not_create_history() -> None:
    repository, factory = _repository()
    service = FxHistorySyncService(FakeFxClient(), repository, mexico_today=lambda: date(2026, 8, 29))

    with pytest.raises(RuntimeError, match="no usable"):
        service.sync()

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(USDMXNRateORM)) == 0
