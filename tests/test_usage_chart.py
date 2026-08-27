from decimal import Decimal

from dash.development.base_component import Component

from app.pages.usage import (
    _aggregate_allocation_rows,
    _analysis_kpis,
    _anthropic_over_time_graph,
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
    assert all(
        trace.hovertemplate == "%{fullData.name}<br>Tokens=%{customdata[0]}<extra></extra>" for trace in figure.data
    )


def test_token_usage_hover_displays_rounded_integer_thousands() -> None:
    rows = [
        {"date": "2026-08-19", "api_key_name": "production-api-key", "total_tokens": 126_999},
        {"date": "2026-08-20", "api_key_name": "production-api-key", "total_tokens": 1_234_567},
    ]

    figure = _token_usage_figure(rows, "api_key")

    assert list(figure.data[0].customdata[:, 0]) == ["127k", "1,235k"]


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
    assert all(
        trace.hovertemplate == "%{fullData.name}<br>Cost (USD)=$%{y:,.2f}<extra></extra>" for trace in figure.data
    )


def test_monthly_usage_groups_dates_and_api_key_series() -> None:
    rows = [
        {"date": "2026-07-31", "api_key_name": "production-api-key", "total_tokens": 100_000},
        {"date": "2026-08-03", "api_key_name": "production-api-key", "total_tokens": 125_000},
        {"date": "2026-08-20", "api_key_name": "production-api-key", "total_tokens": 75_000},
        {"date": "2026-08-20", "api_key_name": "dev-api-key", "total_tokens": 50_000},
    ]

    figure = _token_usage_figure(rows, "api_key", "monthly")

    assert list(figure.layout.xaxis.categoryarray) == ["2026-07", "2026-08"]
    assert figure.layout.xaxis.title.text == "Month (UTC)"
    production_trace = next(trace for trace in figure.data if trace.name == "production-api-key")
    assert list(production_trace.x) == ["2026-07", "2026-08"]
    assert list(production_trace.y) == [100_000, 200_000]


def test_yearly_cost_groups_dates_and_preserves_total() -> None:
    rows = [
        {"date": "2026-07-31", "api_key_name": "production-api-key", "allocated_cost_usd": "1.25"},
        {"date": "2026-08-03", "api_key_name": "production-api-key", "allocated_cost_usd": "2.75"},
        {"date": "2027-01-10", "api_key_name": "production-api-key", "allocated_cost_usd": "3.00"},
    ]

    figure = _cost_over_time_figure(rows, "api_key", "yearly")

    assert list(figure.layout.xaxis.categoryarray) == ["2026", "2027"]
    assert figure.layout.xaxis.title.text == "Year (UTC)"
    assert list(figure.data[0].y) == [4.0, 3.0]
    assert sum(sum(trace.y) for trace in figure.data) == 7.0


def test_summary_table_formats_token_columns_in_thousands() -> None:
    rows = [
        {
            "api_key_name": "production-api-key",
            "uncached_input_tokens": 385_798,
            "cache_creation_1h_tokens": 10_000,
            "cache_creation_5m_tokens": 2_500,
            "cache_read_tokens": 50_050,
            "output_tokens": 96_023,
            "total_tokens": 544_371,
            "web_search_requests": 3,
            "allocated_cost_usd": "2.444",
        }
    ]

    summary = _aggregate_allocation_rows(rows, "api_key")[0]

    assert summary["uncached_input_tokens"] == "385.8k"
    assert summary["cache_creation_tokens"] == "12.5k"
    assert summary["cache_read_tokens"] == "50.0k"
    assert summary["output_tokens"] == "96.0k"
    assert summary["total_tokens"] == "544.4k"
    assert summary["web_search_requests"] == 3
    assert summary["allocated_cost_usd"] == "$2.44 USD"


def test_chart_metric_selects_usage_or_cost_without_duplicating_the_plot() -> None:
    row = {
        "date": "2026-08-03",
        "api_key_name": "production-api-key",
        "total_tokens": 50,
        "allocated_cost_usd": "1.25",
    }

    assert _over_time_figure([row], "api_key", "usage").layout.title.text == "Token usage over time"
    assert _over_time_figure([row], "api_key", "cost").layout.title.text == "Allocated cost over time"


def test_over_time_graph_keeps_a_stable_height_during_group_changes() -> None:
    graph = _anthropic_over_time_graph()

    assert graph.style == {"height": "32rem", "minHeight": "32rem"}
    assert graph.config["responsive"] is True


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
    granularity = next(
        component
        for component in _walk(_chart_metric_control())
        if getattr(component, "id", "") == "anthropic-chart-granularity"
    )
    assert granularity.value == "daily"
    assert granularity.persistence_type == "session"
