from decimal import Decimal

from dash.development.base_component import Component

from app.pages.usage import (
    _analysis_kpis,
    _chart_metric_control,
    _cost_over_time_figure,
    _over_time_figure,
    _token_usage_figure,
)


def _walk(component):
    yield component
    if not isinstance(component, Component):
        return
    children = getattr(component, "children", None)
    if children is None:
        return
    for child in children if isinstance(children, (list, tuple)) else [children]:
        yield from _walk(child)


def test_token_usage_chart_orders_dates_across_api_key_series() -> None:
    rows = [
        {"date": "2026-08-03", "api_key_name": "production-api-key", "total_tokens": 50},
        {"date": "2026-08-07", "api_key_name": "production-api-key", "total_tokens": 75},
        {"date": "2026-08-05", "api_key_name": "dev-api-key", "total_tokens": 25},
    ]

    figure = _token_usage_figure(rows, "api_key")

    assert figure.layout.xaxis.categoryorder == "array"
    assert list(figure.layout.xaxis.categoryarray) == ["2026-08-03", "2026-08-05", "2026-08-07"]


def test_cost_chart_uses_the_same_grouping_and_chronological_order() -> None:
    rows = [
        {"date": "2026-08-03", "api_key_name": "production-api-key", "allocated_cost_usd": "1.25"},
        {"date": "2026-08-07", "api_key_name": "production-api-key", "allocated_cost_usd": "2.75"},
        {"date": "2026-08-05", "api_key_name": "dev-api-key", "allocated_cost_usd": "2.00"},
    ]

    figure = _cost_over_time_figure(rows, "api_key")

    assert list(figure.layout.xaxis.categoryarray) == ["2026-08-03", "2026-08-05", "2026-08-07"]
    assert sum(sum(trace.y) for trace in figure.data) == 6.0
    assert figure.layout.yaxis.tickprefix == "$"


def test_chart_metric_selects_usage_or_cost_without_duplicating_the_plot() -> None:
    row = {
        "date": "2026-08-03",
        "api_key_name": "production-api-key",
        "total_tokens": 50,
        "allocated_cost_usd": "1.25",
    }

    assert _over_time_figure([row], "api_key", "usage").layout.title.text == "Token usage over time"
    assert _over_time_figure([row], "api_key", "cost").layout.title.text == "Allocated cost over time"


def test_cost_disclaimer_is_attached_to_kpi_and_chart_toggle_is_compact() -> None:
    disclaimer = "Costs are allocated proportionally."
    kpis = _analysis_kpis(100, 20, 0, Decimal("1.25"), disclaimer)
    tooltip = next(
        component
        for component in _walk(kpis)
        if getattr(component, "id", "") == "anthropic-allocated-billed-cost-tooltip"
    )

    assert tooltip.children == disclaimer
    assert "anthropic-chart-toolbar" in _chart_metric_control().className
