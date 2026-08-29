from datetime import date, datetime
from decimal import Decimal

import pytest

from app.data.repositories import SeedRepository
from app.domain.cost_engine import (
    calculate_fixed_costs,
    calculate_variable_cost,
    monthly_cost_amounts,
)
from app.domain.fx_rates import (
    USD_MXN_FIX_SERIES_ID,
    DatedFxRateBook,
    FxRateObservation,
    FxRateUnavailableError,
)
from app.domain.models import CostItem, UsageEvent


def _rate_book(*rows: tuple[date, str]) -> DatedFxRateBook:
    return DatedFxRateBook(
        [FxRateObservation(USD_MXN_FIX_SERIES_ID, rate_date, Decimal(rate)) for rate_date, rate in rows]
    )


def _cost(**overrides) -> CostItem:
    values = {
        "id": 1,
        "cost_key": "software.usd",
        "name": "USD subscription",
        "category": "Software",
        "cost_type": "fixed",
        "charge_basis": "flat",
        "quantity": Decimal("1"),
        "unit_cost": Decimal("999"),
        "entered_unit_cost": Decimal("10"),
        "unit": "month",
        "billing_frequency": "monthly",
        "start_date": date(2026, 1, 1),
        "currency": "MXN",
        "entered_currency": "USD",
    }
    values.update(overrides)
    return CostItem(**values)


def _usage(event_id: int, event_date: date, quantity: str = "1") -> UsageEvent:
    return UsageEvent(
        id=event_id,
        client_id=1,
        service_code="ai",
        event_type="ai.token",
        quantity=Decimal(quantity),
        unit="token",
        event_timestamp=datetime.combine(event_date, datetime.min.time()),
        source_system="test",
    )


def test_rate_book_uses_exact_or_latest_prior_rate_without_looking_forward() -> None:
    rates = _rate_book((date(2026, 5, 29), "18"), (date(2026, 6, 1), "19"))

    assert rates.resolve("USD", date(2026, 5, 29)).rate == Decimal("18")
    weekend = rates.resolve("USD", date(2026, 5, 31))
    assert weekend.rate == Decimal("18")
    assert weekend.observation_date == date(2026, 5, 29)
    assert rates.resolve("USD", date(2026, 6, 1)).rate == Decimal("19")


def test_rate_book_rejects_missing_and_stale_rates() -> None:
    rates = _rate_book((date(2026, 5, 1), "18"))

    with pytest.raises(FxRateUnavailableError, match="on or before"):
        rates.resolve("USD", date(2026, 4, 30))
    with pytest.raises(FxRateUnavailableError, match="8 days old"):
        rates.resolve("USD", date(2026, 5, 9))


def test_mixed_fixed_costs_revalue_only_usd_without_mutating_sources() -> None:
    usd = _cost()
    mxn = _cost(
        id=2,
        cost_key="software.mxn",
        unit_cost=Decimal("100"),
        entered_unit_cost=Decimal("100"),
        entered_currency="MXN",
    )
    rates = _rate_book((date(2026, 5, 29), "20"))

    assert calculate_fixed_costs([usd, mxn], date(2026, 5, 1), rates) == Decimal("300")
    assert usd.unit_cost == Decimal("999")
    assert usd.entered_unit_cost == Decimal("10")
    assert mxn.unit_cost == Decimal("100")


def test_fixed_cost_frequency_uses_month_end_and_one_time_dates() -> None:
    monthly = _cost(id=1)
    annual = _cost(id=2, cost_key="software.annual", billing_frequency="annual", start_date=date(2025, 5, 10))
    one_time = _cost(
        id=3,
        cost_key="software.once",
        billing_frequency="once",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 15),
    )
    rates = _rate_book((date(2026, 5, 15), "18"), (date(2026, 5, 31), "20"))

    amounts = monthly_cost_amounts([monthly, annual, one_time], date(2026, 5, 1), fx_rates=rates)

    assert sum((row.amount for row in amounts), Decimal("0")) == Decimal("580")
    by_key = {row.cost_key: row for row in amounts}
    assert by_key["software.usd"].valuation_date == date(2026, 5, 31)
    assert by_key["software.annual"].fx_rate == Decimal("20")
    assert by_key["software.once"].valuation_date == date(2026, 5, 15)
    assert by_key["software.once"].fx_rate == Decimal("18")


def test_current_month_fixed_cost_is_valued_today_and_marked_provisional() -> None:
    rates = _rate_book((date(2026, 8, 28), "17"))

    amount = monthly_cost_amounts(
        [_cost()],
        date(2026, 8, 1),
        fx_rates=rates,
        today=date(2026, 8, 29),
    )[0]

    assert amount.amount == Decimal("170")
    assert amount.valuation_date == date(2026, 8, 29)
    assert amount.fx_rate_date == date(2026, 8, 28)
    assert amount.provisional_fx is True


def test_usd_variable_cost_uses_each_event_date_and_ignores_normalized_snapshot() -> None:
    cost = _cost(
        cost_type="variable",
        charge_basis="usage",
        billing_frequency="usage",
        unit="ai.token",
        entered_unit_cost=Decimal("2"),
        unit_cost=Decimal("999"),
    )
    usage = [_usage(1, date(2026, 5, 1)), _usage(2, date(2026, 5, 2))]
    rates = _rate_book((date(2026, 5, 1), "18"), (date(2026, 5, 2), "20"))

    assert calculate_variable_cost(usage, [cost], rates) == Decimal("76")
    amounts = monthly_cost_amounts([cost], date(2026, 5, 1), usage, rates)
    assert [row.amount for row in amounts] == [Decimal("36"), Decimal("40")]
    assert [row.fx_rate for row in amounts] == [Decimal("18"), Decimal("20")]
    assert cost.unit_cost == Decimal("999")


def test_mxn_costs_do_not_require_fx_history() -> None:
    mxn = _cost(unit_cost=Decimal("125"), entered_unit_cost=Decimal("125"), entered_currency="MXN")

    assert calculate_fixed_costs([mxn], date(2026, 5, 1)) == Decimal("125")


def test_usd_cost_without_original_amount_fails_clearly() -> None:
    usd = _cost(entered_unit_cost=None)

    with pytest.raises(FxRateUnavailableError, match="missing its entered_unit_cost"):
        calculate_fixed_costs([usd], date(2026, 5, 1), _rate_book((date(2026, 5, 31), "20")))


class _CountingFxRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def rate_book(self, starting_at: date, ending_at: date) -> DatedFxRateBook:
        self.calls.append((starting_at, ending_at))
        return _rate_book((starting_at, "18"), (ending_at, "19"))


def test_repository_reuses_bulk_fx_context_and_skips_it_for_mxn() -> None:
    fx_repository = _CountingFxRepository()
    repository = SeedRepository(fx_rate_repository=fx_repository)  # type: ignore[arg-type]
    usd = _cost()
    mxn = _cost(entered_currency="MXN", entered_unit_cost=Decimal("999"))

    first = repository._dated_fx_rates([usd], [date(2026, 5, 1), date(2026, 5, 31)])
    second = repository._dated_fx_rates([usd], [date(2026, 5, 15)])
    mxn_result = repository._dated_fx_rates([mxn], [date(2026, 5, 15)])

    assert first is second
    assert mxn_result is None
    assert fx_repository.calls == [(date(2026, 5, 1), date(2026, 5, 31))]
