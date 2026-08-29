from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.fx_rates import FxRateUnavailableError, ResolvedFxRate
from app.domain.models import CostItem, UsageEvent
from app.domain.unit_economics import money

SAREMI_VALIDATION_UNIT = "saremi.validation"
_SAREMI_VALIDATION_EVENT_TYPES = {
    SAREMI_VALIDATION_UNIT,
    "saremi.ine_validation",
    "saremi.curp_validation",
    "saremi.rfc_validation",
}


def normalize_cost_unit(unit: str) -> str:
    """Map equivalent usage events to the cost unit used for pricing."""

    return SAREMI_VALIDATION_UNIT if unit in _SAREMI_VALIDATION_EVENT_TYPES else unit


@dataclass(frozen=True)
class CostAmount:
    cost_key: str
    name: str
    provider: str | None
    category: str
    service_line: str
    cost_type: str
    charge_basis: str
    quantity: Decimal
    unit_cost: Decimal
    currency: str
    unit: str
    billing_frequency: str
    start_date: date | None
    end_date: date | None
    record_type: str
    amount: Decimal
    source_unit_cost: Decimal
    source_currency: str
    fx_rate: Decimal | None = None
    valuation_date: date | None = None
    fx_rate_date: date | None = None
    provisional_fx: bool = False


class FxRateResolver(Protocol):
    def resolve(self, currency: str, valuation_date: date) -> ResolvedFxRate: ...


@dataclass(frozen=True)
class ValuedUnitCost:
    unit_cost_mxn: Decimal
    source_unit_cost: Decimal
    source_currency: str
    valuation_date: date
    fx_rate: Decimal | None
    fx_rate_date: date | None
    provisional: bool = False


class CostOverlapError(ValueError):
    """Raised when two enabled versions of the same cost key apply to one period."""


def resolve_effective_cost_items(
    cost_items: Iterable[CostItem],
    when: date | datetime,
    *,
    record_type: str = "actual",
    cost_types: set[str] | None = None,
    month_scope: bool = False,
) -> list[CostItem]:
    """Return the single applicable version for each cost key at a date or month.

    Multiple different cost keys can map to the same usage unit. Multiple enabled
    versions of one cost key in the same period are rejected to avoid double-counting.
    """

    applicable_by_key: dict[str, list[CostItem]] = {}
    for item in cost_items:
        if item.record_type != record_type:
            continue
        if cost_types is not None and item.cost_type not in cost_types:
            continue
        if is_cost_effective(item, when, month_scope=month_scope):
            applicable_by_key.setdefault(item.cost_key, []).append(item)

    resolved: list[CostItem] = []
    for cost_key, versions in applicable_by_key.items():
        if len(versions) > 1:
            version_ids = ", ".join(str(item.id) for item in sorted(versions, key=lambda item: item.id))
            raise CostOverlapError(f"Overlapping effective cost records for cost_key '{cost_key}': ids {version_ids}")
        resolved.extend(versions)
    return resolved


def calculate_variable_cost(
    usage_events: Iterable[UsageEvent],
    cost_rates: Mapping[str, Decimal] | Iterable[CostItem],
    fx_rates: FxRateResolver | None = None,
    *,
    use_stored_values: bool = False,
) -> Decimal:
    """Calculate variable cost by multiplying event quantity by matching unit rate."""

    total = Decimal("0")
    for event in usage_events:
        rates = _normalize_rates(
            cost_rates,
            event.event_timestamp,
            fx_rates,
            use_stored_values=use_stored_values,
        )
        rate = rates.get(normalize_cost_unit(event.event_type), Decimal("0"))
        total += money(event.quantity) * money(rate)
    return total


def calculate_fixed_costs(
    cost_items: Iterable[CostItem],
    month: date | None = None,
    fx_rates: FxRateResolver | None = None,
    *,
    today: date | None = None,
    use_stored_values: bool = False,
) -> Decimal:
    month = month or date.today().replace(day=1)
    return sum(
        (
            _fixed_cost_for_month(
                item,
                month,
                fx_rates,
                today=today,
                use_stored_values=use_stored_values,
            )
            for item in resolve_effective_cost_items(
                cost_items,
                month,
                cost_types={"fixed"},
                month_scope=True,
            )
        ),
        Decimal("0"),
    )


def monthly_cost_amounts(
    cost_items: Iterable[CostItem],
    month: date,
    usage_events: Iterable[UsageEvent] = (),
    fx_rates: FxRateResolver | None = None,
    *,
    today: date | None = None,
) -> list[CostAmount]:
    """Calculate actual monthly costs from the catalog and usage events."""

    items = list(cost_items)
    amounts: list[CostAmount] = []
    for item in resolve_effective_cost_items(items, month, cost_types={"fixed"}, month_scope=True):
        amount = _fixed_cost_for_month(item, month, fx_rates, today=today)
        if amount:
            valuation_date = fixed_cost_valuation_date(item, month, today=today)
            valued = value_cost_unit(
                item,
                valuation_date,
                fx_rates,
                provisional=_is_provisional_fixed_valuation(item, month, today=today),
            )
            amounts.append(_cost_amount(item, amount, valued))

    variable_by_item_date: dict[tuple[int, date], tuple[Decimal, ValuedUnitCost]] = {}
    events = list(usage_events)
    for event in events:
        for item in resolve_effective_cost_items(
            items,
            event.event_timestamp,
            cost_types={"variable"},
        ):
            if normalize_cost_unit(item.unit) == normalize_cost_unit(event.event_type):
                valuation_date = event.event_timestamp.date()
                valued = value_cost_unit(item, valuation_date, fx_rates)
                key = (item.id, valuation_date)
                prior_amount = variable_by_item_date.get(key, (Decimal("0"), valued))[0]
                variable_by_item_date[key] = (
                    prior_amount + money(event.quantity) * money(valued.unit_cost_mxn),
                    valued,
                )

    items_by_id = {item.id: item for item in items}
    for (item_id, _valuation_date), (amount, valued) in variable_by_item_date.items():
        amounts.append(_cost_amount(items_by_id[item_id], amount, valued))
    return amounts


def _fixed_cost_for_month(
    item: CostItem,
    month: date,
    fx_rates: FxRateResolver | None = None,
    *,
    today: date | None = None,
    use_stored_values: bool = False,
) -> Decimal:
    if item.record_type != "actual" or not is_cost_effective(item, month, month_scope=True):
        return Decimal("0")
    if not fixed_cost_occurs(item, month):
        return Decimal("0")
    valued = value_cost_unit(
        item,
        fixed_cost_valuation_date(item, month, today=today),
        fx_rates,
        use_stored_values=use_stored_values,
        provisional=_is_provisional_fixed_valuation(item, month, today=today),
    )
    return money(item.quantity * valued.unit_cost_mxn)


def fixed_cost_occurs(item: CostItem, month: date) -> bool:
    if item.billing_frequency == "monthly":
        return True
    if item.billing_frequency == "annual":
        return item.start_date is not None and item.start_date.month == month.month
    if item.billing_frequency == "once":
        return (
            item.start_date is not None and item.start_date.year == month.year and item.start_date.month == month.month
        )
    return False


def fixed_cost_valuation_date(item: CostItem, month: date, *, today: date | None = None) -> date:
    """Return the accounting date used solely to value a fixed-cost occurrence."""

    if item.billing_frequency == "once":
        if item.start_date is None:
            raise ValueError(f"One-time cost item '{item.cost_key}' requires a start date for FX valuation.")
        return item.start_date
    month_end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    current_date = today or mexico_today()
    if (month.year, month.month) == (current_date.year, current_date.month):
        return current_date
    return month_end


def _is_provisional_fixed_valuation(item: CostItem, month: date, *, today: date | None = None) -> bool:
    if item.billing_frequency == "once":
        return False
    current_date = today or mexico_today()
    return (month.year, month.month) == (current_date.year, current_date.month)


def mexico_today() -> date:
    return datetime.now(ZoneInfo("America/Mexico_City")).date()


def is_cost_effective(item: CostItem, when: date | datetime, *, month_scope: bool = False) -> bool:
    """Return whether an actual cost version applies on a date.

    By default the exact day is used. Month-level calculations can explicitly
    request overlap semantics with ``month_scope=True``.
    """

    when_date = when.date() if isinstance(when, datetime) else when
    period_end = when_date
    if month_scope:
        next_month = (when_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        period_end = next_month - timedelta(days=1)
    return _is_cost_effective_on_day(item, when_date, period_end)


def _is_cost_effective_on_day(item: CostItem, when: date, period_end: date | None = None) -> bool:
    period_end = period_end or when
    return (
        item.enabled
        and item.record_type == "actual"
        and (item.start_date is None or item.start_date <= period_end)
        and (item.end_date is None or item.end_date >= when)
    )


def _normalize_rates(
    cost_rates: Mapping[str, Decimal] | Iterable[CostItem],
    when: date | datetime,
    fx_rates: FxRateResolver | None = None,
    *,
    use_stored_values: bool = False,
) -> dict[str, Decimal]:
    if isinstance(cost_rates, Mapping):
        rates: dict[str, Decimal] = {}
        for unit, value in cost_rates.items():
            key = normalize_cost_unit(unit)
            rates[key] = rates.get(key, Decimal("0")) + money(value)
        return rates
    rates: dict[str, Decimal] = {}
    for item in resolve_effective_cost_items(cost_rates, when, cost_types={"variable"}):
        key = normalize_cost_unit(item.unit)
        valued = value_cost_unit(
            item,
            when.date() if isinstance(when, datetime) else when,
            fx_rates,
            use_stored_values=use_stored_values,
        )
        rates[key] = rates.get(key, Decimal("0")) + money(valued.unit_cost_mxn)
    return rates


def value_cost_unit(
    item: CostItem,
    valuation_date: date,
    fx_rates: FxRateResolver | None,
    *,
    use_stored_values: bool = False,
    provisional: bool = False,
) -> ValuedUnitCost:
    source_currency = (item.entered_currency or item.currency).strip().upper()
    source_unit_cost = item.entered_unit_cost if item.entered_unit_cost is not None else item.unit_cost
    if use_stored_values:
        return ValuedUnitCost(
            item.unit_cost, source_unit_cost, source_currency, valuation_date, None, None, provisional
        )
    if source_currency == "MXN":
        return ValuedUnitCost(
            item.unit_cost, source_unit_cost, source_currency, valuation_date, None, None, provisional
        )
    if source_currency != "USD":
        raise FxRateUnavailableError(f"Unsupported entered currency '{source_currency}' for cost '{item.cost_key}'.")
    if item.entered_unit_cost is None:
        raise FxRateUnavailableError(f"USD cost item '{item.cost_key}' is missing its entered_unit_cost source amount.")
    if fx_rates is None:
        raise FxRateUnavailableError(
            f"USD/MXN FIX history is required to value cost '{item.cost_key}' on {valuation_date.isoformat()}."
        )
    resolved = fx_rates.resolve(source_currency, valuation_date)
    return ValuedUnitCost(
        item.entered_unit_cost * resolved.rate,
        item.entered_unit_cost,
        source_currency,
        valuation_date,
        resolved.rate,
        resolved.observation_date,
        provisional,
    )


def _cost_amount(item: CostItem, amount: Decimal, valued: ValuedUnitCost) -> CostAmount:
    return CostAmount(
        cost_key=item.cost_key,
        name=item.name,
        provider=item.provider,
        category=item.category,
        service_line=item.service_line or "Shared",
        cost_type=item.cost_type,
        charge_basis=item.charge_basis,
        quantity=item.quantity,
        unit_cost=item.display_unit_cost,
        currency=item.display_currency,
        unit=item.unit,
        billing_frequency=item.billing_frequency,
        start_date=item.start_date,
        end_date=item.end_date,
        record_type=item.record_type,
        amount=money(amount),
        source_unit_cost=valued.source_unit_cost,
        source_currency=valued.source_currency,
        fx_rate=valued.fx_rate,
        valuation_date=valued.valuation_date,
        fx_rate_date=valued.fx_rate_date,
        provisional_fx=valued.provisional,
    )
