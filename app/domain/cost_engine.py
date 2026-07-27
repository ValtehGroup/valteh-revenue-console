from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.domain.models import CostItem, UsageEvent
from app.domain.unit_economics import money


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
) -> Decimal:
    """Calculate variable cost by multiplying event quantity by matching unit rate."""

    total = Decimal("0")
    for event in usage_events:
        rates = _normalize_rates(cost_rates, event.event_timestamp)
        rate = rates.get(event.event_type, Decimal("0"))
        total += money(event.quantity) * money(rate)
    return total


def calculate_fixed_costs(cost_items: Iterable[CostItem], month: date | None = None) -> Decimal:
    month = month or date.today().replace(day=1)
    return sum(
        (
            _fixed_cost_for_month(item, month)
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
) -> list[CostAmount]:
    """Calculate actual monthly costs from the catalog and usage events."""

    items = list(cost_items)
    amounts: list[CostAmount] = []
    for item in resolve_effective_cost_items(items, month, cost_types={"fixed"}, month_scope=True):
        amount = _fixed_cost_for_month(item, month)
        if amount:
            amounts.append(_cost_amount(item, amount))

    variable_by_item: dict[int, Decimal] = {}
    events = list(usage_events)
    for event in events:
        for item in resolve_effective_cost_items(
            items,
            event.event_timestamp,
            cost_types={"variable"},
        ):
            if item.unit == event.event_type:
                variable_by_item[item.id] = variable_by_item.get(item.id, Decimal("0")) + (
                    money(event.quantity) * money(item.unit_cost)
                )

    items_by_id = {item.id: item for item in items}
    for item_id, amount in variable_by_item.items():
        amounts.append(_cost_amount(items_by_id[item_id], amount))
    return amounts


def _fixed_cost_for_month(item: CostItem, month: date) -> Decimal:
    if item.record_type != "actual" or not is_cost_effective(item, month, month_scope=True):
        return Decimal("0")
    if item.billing_frequency == "monthly":
        return money(item.configured_amount)
    if item.billing_frequency == "annual" and item.start_date and item.start_date.month == month.month:
        return money(item.configured_amount)
    if item.billing_frequency == "once" and item.start_date:
        if item.start_date.year == month.year and item.start_date.month == month.month:
            return money(item.configured_amount)
    return Decimal("0")


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
) -> dict[str, Decimal]:
    if isinstance(cost_rates, Mapping):
        return {key: money(value) for key, value in cost_rates.items()}
    rates: dict[str, Decimal] = {}
    for item in resolve_effective_cost_items(cost_rates, when, cost_types={"variable"}):
        key = item.unit
        rates[key] = rates.get(key, Decimal("0")) + money(item.unit_cost)
    return rates


def _cost_amount(item: CostItem, amount: Decimal) -> CostAmount:
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
    )
