from datetime import date, datetime
from decimal import Decimal

import pytest

from app.data.repositories import SeedRepository
from app.domain.cost_engine import CostAmount
from app.domain.display_currency import (
    format_compact_currency,
    normalize_display_currency,
    translate_cost_amount,
    translate_mxn,
)
from app.domain.fx_rates import ResolvedFxRate
from app.domain.models import ClientSubscription, PricingPlan, UsageEvent
from app.domain.revenue_engine import RevenueAmount, revenue_amounts
from app.domain.scenario_forecast import ScenarioMonth
from app.layout import app_layout
from app.pages.scenarios import _forecast_frame, _table_rows


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)


def _cost(amount: str, recognition_date: date, *, source_currency: str = "MXN", fx_rate=None):
    return CostAmount(
        cost_key=f"cost.{source_currency.lower()}",
        name="Cost",
        provider="Provider",
        category="Software",
        service_line="Shared",
        cost_type="fixed",
        charge_basis="flat",
        quantity=Decimal("1"),
        unit_cost=Decimal(amount),
        currency=source_currency,
        unit="month",
        billing_frequency="monthly",
        start_date=date(2026, 1, 1),
        end_date=None,
        record_type="actual",
        amount=Decimal(amount),
        source_unit_cost=Decimal(amount),
        source_currency=source_currency,
        fx_rate=fx_rate,
        valuation_date=recognition_date,
        fx_rate_date=recognition_date,
    )


def test_display_currency_defaults_to_mxn_and_rejects_other_values() -> None:
    assert normalize_display_currency(None) == "MXN"
    assert normalize_display_currency("usd") == "USD"
    with pytest.raises(ValueError, match="MXN or USD"):
        normalize_display_currency("EUR")


def test_global_currency_control_and_store_are_session_persistent() -> None:
    components = {getattr(component, "id", None): component for component in _walk(app_layout())}

    assert components["display-currency-store"].data == "MXN"
    assert components["display-currency-store"].storage_type == "session"
    assert components["display-currency-toggle"].value == "MXN"
    assert components["display-currency-toggle"].persistence_type == "session"
    assert [option["value"] for option in components["display-currency-toggle"].options] == ["MXN", "USD"]


def test_two_occurrences_in_one_month_use_their_own_fix_and_margin_is_recomputed() -> None:
    revenues = [
        RevenueAmount(1, "SIGEN", "setup", Decimal("200"), date(2026, 8, 1), Decimal("200")),
        RevenueAmount(1, "SAREMI", "usage", Decimal("400"), date(2026, 8, 20), Decimal("400")),
    ]
    costs = [_cost("180", date(2026, 8, 1))]
    rates = {
        date(2026, 8, 1): ResolvedFxRate("USD", date(2026, 8, 1), Decimal("20"), date(2026, 8, 1)),
        date(2026, 8, 20): ResolvedFxRate("USD", date(2026, 8, 20), Decimal("16"), date(2026, 8, 20)),
    }
    repo = object.__new__(SeedRepository)
    repo.monthly_revenue_amounts = lambda _month: revenues
    repo.monthly_cost_amounts = lambda _month: costs
    repo.usd_mxn_rates_for_dates = lambda _dates: rates

    presentation = SeedRepository.monthly_presentation(repo, "2026-08", "USD")

    assert presentation["summary"]["revenue"] == Decimal("35")
    assert presentation["summary"]["fixed_cost"] == Decimal("9")
    assert presentation["summary"]["operating_margin"] == Decimal("26")
    assert sum(presentation["revenue_by_service"].values(), Decimal("0")) == Decimal("35")
    assert sum(presentation["cost_by_provider"].values(), Decimal("0")) == Decimal("9")


def test_usd_source_cost_keeps_the_fix_used_to_create_its_mxn_amount() -> None:
    cost = _cost("180", date(2026, 8, 20), source_currency="USD", fx_rate=Decimal("18"))
    other_rate = {date(2026, 8, 20): ResolvedFxRate("USD", date(2026, 8, 20), Decimal("20"), date(2026, 8, 20))}

    assert translate_cost_amount(cost, "USD", other_rate) == Decimal("10")


def test_revenue_occurrences_use_subscription_and_usage_recognition_dates() -> None:
    plan = PricingPlan(
        id=1,
        name="Plan",
        setup_fee=Decimal("100"),
        annual_fee=Decimal("120"),
        monthly_fixed_fee=Decimal("50"),
        price_per_document=Decimal("2"),
    )
    subscription = ClientSubscription(
        id=1,
        client_id=7,
        pricing_plan_id=1,
        start_date=date(2026, 8, 5),
    )
    usage = [
        UsageEvent(
            id=1,
            client_id=7,
            service_code="saremi",
            event_type="saremi.document_validation",
            quantity=Decimal("3"),
            unit="document",
            event_timestamp=datetime(2026, 8, 12),
            source_system="test",
        )
    ]

    amounts = revenue_amounts(usage, plan, subscription, date(2026, 8, 1), today=date(2026, 8, 20))
    dates_by_type = {amount.revenue_type: amount.recognition_date for amount in amounts}
    anniversary_subscription = subscription.model_copy(update={"start_date": date(2025, 8, 5)})
    anniversary_amounts = revenue_amounts([], plan, anniversary_subscription, date(2026, 8, 1), today=date(2026, 8, 20))
    annual = next(amount for amount in anniversary_amounts if amount.revenue_type == "annual")

    assert dates_by_type["monthly_subscription"] == date(2026, 8, 20)
    assert dates_by_type["setup"] == date(2026, 8, 5)
    assert annual.recognition_date == date(2026, 8, 5)
    assert dates_by_type["usage"] == date(2026, 8, 12)
    assert next(amount for amount in amounts if amount.revenue_type == "monthly_subscription").provisional_fx


def test_decimal_translation_and_currency_formatting() -> None:
    assert translate_mxn(Decimal("100"), "USD", Decimal("3")) == Decimal("100") / Decimal("3")
    assert format_compact_currency(Decimal("1555"), "USD") == "$1.6k USD"


def test_scenario_usd_presentation_uses_each_rows_assumption_without_changing_table() -> None:
    rows = [
        ScenarioMonth(
            scenario="Base",
            month="2026-09",
            clients=2,
            revenue=Decimal("200"),
            fixed_cost=Decimal("80"),
            variable_cost=Decimal("20"),
            operating_margin=Decimal("100"),
            usd_mxn_rate=Decimal("20"),
        ),
        ScenarioMonth(
            scenario="Optimistic",
            month="2026-09",
            clients=3,
            revenue=Decimal("200"),
            fixed_cost=Decimal("80"),
            variable_cost=Decimal("20"),
            operating_margin=Decimal("100"),
            usd_mxn_rate=Decimal("16"),
        ),
    ]

    frame = _forecast_frame(rows, "USD")

    assert list(frame["revenue"]) == [10.0, 12.5]
    assert _table_rows(rows)[0]["revenue"] == "$200 MXN"
    assert [row.clients for row in rows] == [2, 3]
