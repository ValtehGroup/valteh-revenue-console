from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

USD_MXN_FIX_SERIES_ID = "SF43718"


@dataclass(frozen=True)
class FxRateObservation:
    series_id: str
    rate_date: date
    rate: Decimal
    source: str = "banxico_sie"


@dataclass(frozen=True)
class FxRateUpsertResult:
    inserted: int
    updated: int


@dataclass(frozen=True)
class FxRateStatus:
    latest: FxRateObservation | None
    last_refreshed_at: datetime | None


class FxRateUnavailableError(ValueError):
    """Raised when a dated currency conversion cannot be supported safely."""


@dataclass(frozen=True)
class ResolvedFxRate:
    currency: str
    valuation_date: date
    rate: Decimal
    observation_date: date | None


class DatedFxRateBook:
    """Resolve persisted FX observations without performing I/O."""

    def __init__(self, observations: list[FxRateObservation], *, maximum_age_days: int = 7) -> None:
        if maximum_age_days < 0:
            raise ValueError("Maximum FX age must be non-negative.")
        ordered = sorted(observations, key=lambda observation: observation.rate_date)
        dates = [observation.rate_date for observation in ordered]
        if len(dates) != len(set(dates)):
            raise ValueError("FX observations contain duplicate dates.")
        for observation in ordered:
            if observation.series_id != USD_MXN_FIX_SERIES_ID:
                raise ValueError(f"Unexpected FX series '{observation.series_id}'.")
            if not observation.rate.is_finite() or observation.rate <= 0:
                raise ValueError("FX observations must contain positive finite rates.")
        self._observations = tuple(ordered)
        self._dates = tuple(dates)
        self._maximum_age_days = maximum_age_days

    def resolve(self, currency: str, valuation_date: date) -> ResolvedFxRate:
        currency_code = currency.strip().upper()
        if currency_code == "MXN":
            return ResolvedFxRate(currency_code, valuation_date, Decimal("1"), None)
        if currency_code != "USD":
            raise FxRateUnavailableError(f"Unsupported currency '{currency_code}' for dated FX conversion.")

        index = bisect_right(self._dates, valuation_date) - 1
        if index < 0:
            raise FxRateUnavailableError(f"No USD/MXN FIX rate exists on or before {valuation_date.isoformat()}.")
        observation = self._observations[index]
        age_days = (valuation_date - observation.rate_date).days
        if age_days > self._maximum_age_days:
            raise FxRateUnavailableError(
                f"USD/MXN FIX rate for {valuation_date.isoformat()} is unavailable; "
                f"the latest prior observation is {age_days} days old."
            )
        return ResolvedFxRate(currency_code, valuation_date, observation.rate, observation.rate_date)
