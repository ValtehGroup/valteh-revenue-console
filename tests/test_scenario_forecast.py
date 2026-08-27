from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from dash import dcc

from app.domain.models import CostItem, UsageEvent
from app.domain.scenario_forecast import (
    DEFAULT_REFERENCE_USD_MXN_RATE,
    SCENARIO_CONFIGS,
    ClientEconomicsProfile,
    ScenarioConfig,
    ScenarioMonth,
    cost_items_at_usd_mxn_rate,
    forecast_months,
    forecast_scenarios,
    month_forecast,
    scenario_client_profiles,
    scenario_usd_mxn_rate,
)
from app.pages.scenarios import _exchange_rate_controls, _table_rows


def test_forecast_months_starts_from_base_month() -> None:
    assert forecast_months("2026-06", 6) == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]


def test_built_in_scenarios_define_expected_usd_mxn_rates() -> None:
    assert [
        (config.name, scenario_usd_mxn_rate(config, DEFAULT_REFERENCE_USD_MXN_RATE)) for config in SCENARIO_CONFIGS
    ] == [
        ("Base", Decimal("18")),
        ("Pessimistic", Decimal("21.6")),
        ("Optimistic", Decimal("16.2")),
    ]


def test_pessimistic_drops_largest_client_from_second_month_and_increases_costs() -> None:
    profiles = [
        ClientEconomicsProfile(client_id=1, revenue=Decimal("10000"), variable_cost=Decimal("1000")),
        ClientEconomicsProfile(client_id=2, revenue=Decimal("4000"), variable_cost=Decimal("500")),
    ]
    config = ScenarioConfig(
        name="Pessimistic",
        fixed_cost_multiplier=Decimal("1.10"),
        variable_cost_multiplier=Decimal("1.20"),
        drop_largest_client=True,
    )

    first_month = month_forecast(config, "2026-06", 1, profiles, Decimal("1000"))
    second_month = month_forecast(config, "2026-07", 2, profiles, Decimal("1000"))

    assert first_month.clients == 2
    assert first_month.revenue == Decimal("14000")
    assert first_month.variable_cost == Decimal("1800.00")
    assert second_month.clients == 1
    assert second_month.revenue == Decimal("4000")
    assert second_month.fixed_cost == Decimal("1100.00")
    assert second_month.variable_cost == Decimal("600.00")


def test_optimistic_adds_average_client_from_join_month() -> None:
    profiles = [
        ClientEconomicsProfile(client_id=1, revenue=Decimal("10000"), variable_cost=Decimal("1000")),
        ClientEconomicsProfile(client_id=2, revenue=Decimal("4000"), variable_cost=Decimal("500")),
    ]
    config = ScenarioConfig(name="Optimistic", add_new_client=True, new_client_join_month=4)

    before_join = scenario_client_profiles(config, 3, profiles)
    after_join = scenario_client_profiles(config, 4, profiles)

    assert len(before_join) == 2
    assert len(after_join) == 3
    assert after_join[-1].revenue == Decimal("7000")
    assert after_join[-1].variable_cost == Decimal("750")


def test_forecast_revalues_only_usd_costs_before_applying_scenario_multipliers() -> None:
    forecast = forecast_scenarios(_mixed_currency_repository(), horizon_months=1)
    by_scenario = {row.scenario: row for row in forecast}

    assert by_scenario["Base"].fixed_cost == Decimal("280")
    assert by_scenario["Base"].variable_cost == Decimal("120")
    assert by_scenario["Pessimistic"].fixed_cost == Decimal("347.60000")
    assert by_scenario["Pessimistic"].variable_cost == Decimal("169.920000")
    assert by_scenario["Optimistic"].fixed_cost == Decimal("262.0000")
    assert by_scenario["Optimistic"].variable_cost == Decimal("98.280000")
    assert {row.revenue for row in forecast} == {Decimal("1000")}


def test_custom_reference_rate_changes_all_scenario_fx_rates_and_usd_costs() -> None:
    forecast = forecast_scenarios(
        _mixed_currency_repository(),
        horizon_months=1,
        reference_usd_mxn_rate=Decimal("20"),
    )
    by_scenario = {row.scenario: row for row in forecast}

    assert by_scenario["Base"].usd_mxn_rate == Decimal("20.0000")
    assert by_scenario["Pessimistic"].usd_mxn_rate == Decimal("24.0000")
    assert by_scenario["Optimistic"].usd_mxn_rate == Decimal("18.0000")
    assert by_scenario["Base"].fixed_cost == Decimal("300.0000")
    assert by_scenario["Pessimistic"].fixed_cost == Decimal("374.00000")
    assert by_scenario["Optimistic"].fixed_cost == Decimal("280.0000")


def test_custom_downside_and_upside_percentages_override_default_fx_changes() -> None:
    forecast = forecast_scenarios(
        _mixed_currency_repository(),
        horizon_months=1,
        scenario_usd_mxn_changes={
            "Pessimistic": Decimal("0.30"),
            "Optimistic": Decimal("-0.20"),
        },
    )
    by_scenario = {row.scenario: row for row in forecast}

    assert by_scenario["Base"].usd_mxn_rate == Decimal("18.0000")
    assert by_scenario["Pessimistic"].usd_mxn_rate == Decimal("23.4000")
    assert by_scenario["Optimistic"].usd_mxn_rate == Decimal("14.4000")


def test_cost_revaluation_returns_copies_without_mutating_source_items() -> None:
    source = _cost_item(
        id=1,
        cost_key="fixed.usd",
        unit_cost="180",
        entered_unit_cost="10",
        entered_currency="USD",
    )

    revalued = cost_items_at_usd_mxn_rate([source], Decimal("20"))

    assert revalued[0] is not source
    assert revalued[0].unit_cost == Decimal("200")
    assert revalued[0].entered_unit_cost == Decimal("10")
    assert source.unit_cost == Decimal("180")


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-1")])
def test_scenario_rejects_non_positive_reference_usd_mxn_rate(rate: Decimal) -> None:
    with pytest.raises(ValueError, match="usd_mxn_rate must be greater than zero"):
        scenario_usd_mxn_rate(SCENARIO_CONFIGS[0], rate)


def test_usd_cost_without_entered_amount_is_rejected() -> None:
    source = _cost_item(
        id=1,
        cost_key="fixed.usd",
        unit_cost="180",
        entered_currency="USD",
    )

    with pytest.raises(ValueError, match="fixed.usd.*missing its entered_unit_cost"):
        cost_items_at_usd_mxn_rate([source], Decimal("20"))


def test_scenario_table_exposes_usd_mxn_rate() -> None:
    month = ScenarioMonth(
        scenario="Base",
        month="2026-06",
        usd_mxn_rate=Decimal("18"),
        clients=1,
        revenue=Decimal("1000"),
        fixed_cost=Decimal("280"),
        variable_cost=Decimal("120"),
        operating_margin=Decimal("600"),
    )

    assert _table_rows([month])[0]["usd_mxn_rate"] == "18.00"


def test_scenario_page_has_compact_editable_fx_assumptions() -> None:
    controls = _exchange_rate_controls()
    baseline = _find_component(controls, "scenario-reference-usd-mxn-rate")
    downside = _find_component(controls, "scenario-downside-usd-mxn-change")
    upside = _find_component(controls, "scenario-upside-usd-mxn-change")

    assert baseline is not None
    assert isinstance(baseline, dcc.Input)
    assert baseline.type == "text"
    assert baseline.inputMode == "decimal"
    assert baseline.value == 18.0
    assert baseline.min == 0.01
    assert baseline.step == 0.01
    assert baseline.debounce is False
    assert downside.value == 20.0
    assert downside.step == 0.1
    assert upside.value == -10.0
    assert upside.step == 0.1


def _mixed_currency_repository() -> "_ScenarioRepository":
    cost_items = [
        _cost_item(id=1, cost_key="fixed.mxn", unit_cost="100"),
        _cost_item(
            id=2,
            cost_key="fixed.usd",
            unit_cost="180",
            entered_unit_cost="10",
            entered_currency="USD",
        ),
        _cost_item(
            id=3,
            cost_key="variable.mxn",
            cost_type="variable",
            unit_cost="4",
        ),
        _cost_item(
            id=4,
            cost_key="variable.usd",
            cost_type="variable",
            unit_cost="36",
            entered_unit_cost="2",
            entered_currency="USD",
        ),
    ]
    usage = UsageEvent(
        id=1,
        client_id=1,
        service_code="test",
        event_type="test.usage",
        quantity=Decimal("3"),
        unit="request",
        event_timestamp=datetime(2026, 6, 15),
        source_system="test",
    )
    return _ScenarioRepository(cost_items, usage)


def _find_component(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, list):
        children = [children]
    for child in children:
        match = _find_component(child, component_id)
        if match is not None:
            return match
    return None


def _cost_item(
    *,
    id: int,
    cost_key: str,
    unit_cost: str,
    cost_type: str = "fixed",
    entered_unit_cost: str | None = None,
    entered_currency: str = "MXN",
) -> CostItem:
    is_variable = cost_type == "variable"
    return CostItem(
        id=id,
        cost_key=cost_key,
        name=cost_key,
        category="Test",
        cost_type=cost_type,
        charge_basis="usage" if is_variable else "flat",
        quantity=Decimal("1"),
        unit_cost=Decimal(unit_cost),
        entered_unit_cost=Decimal(entered_unit_cost) if entered_unit_cost is not None else None,
        unit="test.usage" if is_variable else "month",
        billing_frequency="usage" if is_variable else "monthly",
        start_date=date(2026, 6, 1),
        currency="MXN",
        entered_currency=entered_currency,
    )


class _ScenarioRepository:
    def __init__(self, cost_items: list[CostItem], usage: UsageEvent) -> None:
        self._cost_items = cost_items
        self._usage = usage

    def available_months(self) -> list[str]:
        return ["2026-06"]

    def cost_items(self) -> list[CostItem]:
        return self._cost_items

    def active_clients(self, month: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(id=1)]

    def client_profitability(self, client_id: int, month: str) -> SimpleNamespace:
        return SimpleNamespace(revenue=Decimal("1000"), variable_cost=Decimal("120"))

    def usage_for_client_month(self, client_id: int, month: str) -> list[UsageEvent]:
        return [self._usage]
