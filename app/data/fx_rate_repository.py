from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.database import SessionLocal
from app.data.schemas import USDMXNRateORM
from app.domain.fx_rates import (
    USD_MXN_FIX_SERIES_ID,
    DatedFxRateBook,
    FxRateObservation,
    FxRateStatus,
    FxRateUpsertResult,
)

SessionFactory = Callable[[], Session]


class FxRateRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    def status(self) -> FxRateStatus:
        with self._session_factory() as session:
            row = session.scalar(
                select(USDMXNRateORM)
                .where(USDMXNRateORM.series_id == USD_MXN_FIX_SERIES_ID)
                .order_by(USDMXNRateORM.rate_date.desc(), USDMXNRateORM.id.desc())
                .limit(1)
            )
            refreshed_at = session.scalar(
                select(func.max(USDMXNRateORM.updated_at)).where(USDMXNRateORM.series_id == USD_MXN_FIX_SERIES_ID)
            )
            return FxRateStatus(_domain(row) if row is not None else None, refreshed_at)

    def latest(self) -> FxRateObservation | None:
        return self.status().latest

    def observations(self, starting_at: date, ending_at: date) -> list[FxRateObservation]:
        if ending_at < starting_at:
            raise ValueError("End date must be on or after start date.")
        with self._session_factory() as session:
            rows = session.scalars(
                select(USDMXNRateORM)
                .where(
                    USDMXNRateORM.series_id == USD_MXN_FIX_SERIES_ID,
                    USDMXNRateORM.rate_date >= starting_at,
                    USDMXNRateORM.rate_date <= ending_at,
                )
                .order_by(USDMXNRateORM.rate_date)
            ).all()
            return [_domain(row) for row in rows]

    def rate_book(
        self,
        starting_at: date,
        ending_at: date,
        *,
        maximum_age_days: int = 7,
    ) -> DatedFxRateBook:
        """Load one bounded observation set for a dated calculation range."""

        if ending_at < starting_at:
            raise ValueError("End date must be on or after start date.")
        observations = self.observations(starting_at - timedelta(days=maximum_age_days), ending_at)
        return DatedFxRateBook(observations, maximum_age_days=maximum_age_days)

    def upsert(self, observations: Sequence[FxRateObservation]) -> FxRateUpsertResult:
        identities = [(row.series_id, row.rate_date) for row in observations]
        if len(identities) != len(set(identities)):
            raise ValueError("FX observations contain duplicate series dates.")
        if not observations:
            return FxRateUpsertResult(0, 0)
        now = datetime.now(UTC)
        inserted = 0
        updated = 0
        with self._session_factory() as session:
            with session.begin():
                for observation in observations:
                    row = session.scalar(
                        select(USDMXNRateORM).where(
                            USDMXNRateORM.series_id == observation.series_id,
                            USDMXNRateORM.rate_date == observation.rate_date,
                        )
                    )
                    if row is None:
                        session.add(
                            USDMXNRateORM(
                                series_id=observation.series_id,
                                rate_date=observation.rate_date,
                                rate=observation.rate,
                                source=observation.source,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        inserted += 1
                    else:
                        row.rate = observation.rate
                        row.source = observation.source
                        row.updated_at = now
                        updated += 1
        return FxRateUpsertResult(inserted, updated)


def _domain(row: USDMXNRateORM) -> FxRateObservation:
    return FxRateObservation(row.series_id, row.rate_date, row.rate, row.source)
