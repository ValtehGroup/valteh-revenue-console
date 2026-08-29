from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

from app.domain.cost_engine import calculate_fixed_costs, calculate_variable_cost
from app.domain.unit_economics import calculate_operating_margin, money

if TYPE_CHECKING:
    from app.data.repositories import SeedRepository
    from app.domain.models import CostItem


DEFAULT_REFERENCE_USD_MXN_RATE = Decimal("18")
DEFAULT_DOWNSIDE_USD_MXN_CHANGE = Decimal("0.20")
DEFAULT_UPSIDE_USD_MXN_CHANGE = Decimal("-0.10")
USD_MXN_RATE_QUANTUM = Decimal("0.0001")


def _validated_usd_mxn_rate(value: Decimal | float | int | str) -> Decimal:
    rate = money(value)
    if not rate.is_finite() or rate <= 0:
        raise ValueError("usd_mxn_rate must be greater than zero")
    return rate


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    usd_mxn_change: Decimal = Decimal("0")
    fixed_cost_multiplier: Decimal = Decimal("1")
    variable_cost_multiplier: Decimal = Decimal("1")
    drop_largest_client: bool = False
    largest_client_drop_month: int = 2
    add_new_client: bool = False
    new_client_join_month: int = 4

    def __post_init__(self) -> None:
        change = money(self.usd_mxn_change)
        if not change.is_finite() or change <= Decimal("-1"):
            raise ValueError("usd_mxn_change must be greater than -100%")
        object.__setattr__(self, "usd_mxn_change", change)


@dataclass(frozen=True)
class ClientEconomicsProfile:
    client_id: int
    revenue: Decimal
    variable_cost: Decimal


@dataclass(frozen=True)
class ScenarioMonth:
    scenario: str
    month: str
    usd_mxn_rate: Decimal
    clients: int
    revenue: Decimal
    fixed_cost: Decimal
    variable_cost: Decimal
    operating_margin: Decimal


SCENARIO_CONFIGS = [
    ScenarioConfig(name="Base", usd_mxn_change=Decimal("0")),
    ScenarioConfig(
        name="Pessimistic",
        usd_mxn_change=DEFAULT_DOWNSIDE_USD_MXN_CHANGE,
        fixed_cost_multiplier=Decimal("1.10"),
        variable_cost_multiplier=Decimal("1.20"),
        drop_largest_client=True,
    ),
    ScenarioConfig(
        name="Optimistic",
        usd_mxn_change=DEFAULT_UPSIDE_USD_MXN_CHANGE,
        variable_cost_multiplier=Decimal("0.90"),
        add_new_client=True,
        new_client_join_month=4,
    ),
]


def forecast_scenarios(
    repo: SeedRepository,
    horizon_months: int = 6,
    start_month: str | None = None,
    configs: list[ScenarioConfig] | None = None,
    reference_usd_mxn_rate: Decimal = DEFAULT_REFERENCE_USD_MXN_RATE,
    scenario_usd_mxn_changes: Mapping[str, Decimal] | None = None,
) -> list[ScenarioMonth]:
    """Build month-by-month scenario forecasts from the latest available actual month."""

    base_month = start_month or repo.available_months()[-1]
    months = forecast_months(base_month, horizon_months)
    scenario_configs = configs or SCENARIO_CONFIGS
    if scenario_usd_mxn_changes is not None:
        scenario_configs = [
            replace(
                config,
                usd_mxn_change=scenario_usd_mxn_changes.get(config.name, config.usd_mxn_change),
            )
            for config in scenario_configs
        ]
    reference_rate = _validated_usd_mxn_rate(reference_usd_mxn_rate)
    base_cost_items = repo.cost_items()
    base_month_date = pd.Timestamp(f"{base_month}-01").date()
    forecasts: list[ScenarioMonth] = []
    for config in scenario_configs:
        usd_mxn_rate = scenario_usd_mxn_rate(config, reference_rate)
        scenario_cost_items = cost_items_at_usd_mxn_rate(base_cost_items, usd_mxn_rate)
        profiles = current_client_profiles(repo, base_month, scenario_cost_items)
        fixed_cost = calculate_fixed_costs(scenario_cost_items, base_month_date, use_stored_values=True)
        forecasts.extend(
            month_forecast(config, month, month_index, profiles, fixed_cost, usd_mxn_rate)
            for month_index, month in enumerate(months, start=1)
        )
    return forecasts


def scenario_usd_mxn_rate(config: ScenarioConfig, reference_usd_mxn_rate: Decimal) -> Decimal:
    """Apply a scenario's percentage change to the user-selected reference rate."""

    reference_rate = _validated_usd_mxn_rate(reference_usd_mxn_rate)
    return (reference_rate * (Decimal("1") + config.usd_mxn_change)).quantize(USD_MXN_RATE_QUANTUM)


def forecast_months(start_month: str, horizon_months: int) -> list[str]:
    """Return month labels beginning with the latest actual month."""

    period = pd.Period(start_month, freq="M")
    return [str(period + offset) for offset in range(horizon_months)]


def current_client_profiles(
    repo: SeedRepository,
    month: str,
    cost_items: Iterable[CostItem] | None = None,
) -> list[ClientEconomicsProfile]:
    """Capture actual current-month client revenue and variable cost as reusable profiles."""

    scenario_cost_items = list(cost_items) if cost_items is not None else None
    profiles = []
    for client in repo.active_clients(month):
        profitability = repo.client_profitability(client.id, month)
        variable_cost = profitability.variable_cost
        if scenario_cost_items is not None:
            variable_cost = calculate_variable_cost(
                repo.usage_for_client_month(client.id, month),
                scenario_cost_items,
                use_stored_values=True,
            )
        profiles.append(
            ClientEconomicsProfile(
                client_id=client.id,
                revenue=profitability.revenue,
                variable_cost=variable_cost,
            )
        )
    return profiles


def cost_items_at_usd_mxn_rate(
    cost_items: Iterable[CostItem],
    usd_mxn_rate: Decimal,
) -> list[CostItem]:
    """Return detached cost copies with USD source amounts converted at a scenario rate."""

    rate = _validated_usd_mxn_rate(usd_mxn_rate)
    revalued_items = []
    for item in cost_items:
        updates = {}
        if (item.entered_currency or "").strip().upper() == "USD":
            if item.entered_unit_cost is None:
                raise ValueError(f"USD cost item '{item.cost_key}' is missing its entered_unit_cost source amount")
            updates["unit_cost"] = money(item.entered_unit_cost) * rate
        revalued_items.append(item.model_copy(update=updates))
    return revalued_items


def month_forecast(
    config: ScenarioConfig,
    month: str,
    month_index: int,
    base_profiles: list[ClientEconomicsProfile],
    base_fixed_cost: Decimal,
    usd_mxn_rate: Decimal | None = None,
) -> ScenarioMonth:
    """Apply one scenario configuration to one forecast month."""

    applied_usd_mxn_rate = (
        scenario_usd_mxn_rate(config, DEFAULT_REFERENCE_USD_MXN_RATE)
        if usd_mxn_rate is None
        else _validated_usd_mxn_rate(usd_mxn_rate)
    )
    profiles = scenario_client_profiles(config, month_index, base_profiles)
    revenue = sum((profile.revenue for profile in profiles), Decimal("0"))
    variable_cost = sum((profile.variable_cost for profile in profiles), Decimal("0")) * money(
        config.variable_cost_multiplier
    )
    fixed_cost = money(base_fixed_cost) * money(config.fixed_cost_multiplier)
    operating_margin = calculate_operating_margin(revenue, variable_cost, fixed_cost)
    return ScenarioMonth(
        scenario=config.name,
        month=month,
        usd_mxn_rate=applied_usd_mxn_rate,
        clients=len(profiles),
        revenue=revenue,
        fixed_cost=fixed_cost,
        variable_cost=variable_cost,
        operating_margin=operating_margin,
    )


def scenario_client_profiles(
    config: ScenarioConfig,
    month_index: int,
    base_profiles: list[ClientEconomicsProfile],
) -> list[ClientEconomicsProfile]:
    profiles = list(base_profiles)
    if config.drop_largest_client and month_index >= config.largest_client_drop_month and profiles:
        largest_client = max(profiles, key=lambda profile: profile.revenue)
        profiles = [profile for profile in profiles if profile.client_id != largest_client.client_id]
    if config.add_new_client and month_index >= config.new_client_join_month and profiles:
        profiles.append(average_client_profile(profiles, client_id=0))
    return profiles


def average_client_profile(
    profiles: list[ClientEconomicsProfile],
    client_id: int,
) -> ClientEconomicsProfile:
    if not profiles:
        return ClientEconomicsProfile(client_id=client_id, revenue=Decimal("0"), variable_cost=Decimal("0"))
    profile_count = Decimal(len(profiles))
    return ClientEconomicsProfile(
        client_id=client_id,
        revenue=sum((profile.revenue for profile in profiles), Decimal("0")) / profile_count,
        variable_cost=sum((profile.variable_cost for profile in profiles), Decimal("0")) / profile_count,
    )
