from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.fx_rates import FxRateObservation, FxRateUpsertResult

FX_HISTORY_START_DATE = date(2015, 1, 1)
FX_SYNC_OVERLAP_DAYS = 7
MEXICO_CITY_TIMEZONE = ZoneInfo("America/Mexico_City")


class FxRateClient(Protocol):
    def fetch_usd_mxn_fix(self, starting_at: date, ending_at: date) -> Sequence[FxRateObservation]: ...


class FxRateStore(Protocol):
    def latest(self) -> FxRateObservation | None: ...

    def upsert(self, observations: Sequence[FxRateObservation]) -> FxRateUpsertResult: ...


@dataclass(frozen=True)
class FxHistorySyncResult:
    starting_at: date
    ending_at: date
    fetched: int
    inserted: int
    updated: int
    latest: FxRateObservation


class FxHistorySyncService:
    def __init__(
        self,
        client: FxRateClient,
        repository: FxRateStore,
        *,
        mexico_today: Callable[[], date] | None = None,
    ) -> None:
        self._client = client
        self._repository = repository
        self._mexico_today = mexico_today or (lambda: datetime.now(MEXICO_CITY_TIMEZONE).date())

    def sync(self) -> FxHistorySyncResult:
        starting_at, ending_at = resolve_fx_sync_range(self._repository.latest(), self._mexico_today())
        observations = tuple(self._client.fetch_usd_mxn_fix(starting_at, ending_at))
        persisted = self._repository.upsert(observations)
        latest = self._repository.latest()
        if latest is None:
            raise RuntimeError("Banxico returned no usable USD/MXN FIX observations.")
        return FxHistorySyncResult(
            starting_at=starting_at,
            ending_at=ending_at,
            fetched=len(observations),
            inserted=persisted.inserted,
            updated=persisted.updated,
            latest=latest,
        )


def resolve_fx_sync_range(latest: FxRateObservation | None, mexico_today: date) -> tuple[date, date]:
    if mexico_today < FX_HISTORY_START_DATE:
        raise ValueError("The FX synchronization date precedes the configured history start date.")
    if latest is None:
        return FX_HISTORY_START_DATE, mexico_today
    return max(FX_HISTORY_START_DATE, latest.rate_date - timedelta(days=FX_SYNC_OVERLAP_DAYS)), mexico_today
