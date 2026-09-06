from datetime import date
from decimal import Decimal

from dash import html

from app.data.repositories import SeedRepository
from app.layout import NAV_ITEMS
from app.pages import executive_dashboard
from app.pages.executive_dashboard import (
    _dashboard_content,
    _executive_bar_chart,
    _executive_pie_chart,
    _format_mxn_thousands,
    layout,
)


def test_executive_dashboard_is_renamed_to_executive_summary() -> None:
    assert NAV_ITEMS[0] == ("Executive Summary", "/")
    assert "Executive Summary" in str(layout())
    assert "Executive Dashboard" not in str(layout())


def test_executive_bar_chart_exposes_precise_tooltip_data_and_grouped_axis() -> None:
    figure = _executive_bar_chart({"SAREMI": Decimal("1555")}, "Revenue")

    assert figure.data[0].hovertemplate is None
    assert figure.data[0].hoverinfo == "none"
    assert list(figure.data[0].customdata) == ["$1,555.00 MXN"]
    assert figure.layout.yaxis.tickformat == ",.0f"


def test_executive_pie_chart_exposes_precise_tooltip_data() -> None:
    figure = _executive_pie_chart({"SAREMI": Decimal("1555")}, "Revenue")

    assert figure.data[0].hovertemplate is None
    assert figure.data[0].hoverinfo == "none"
    assert list(figure.data[0].customdata) == ["$1,555.00 MXN"]


def test_mxn_hover_format_keeps_one_decimal_in_thousands() -> None:
    assert _format_mxn_thousands(Decimal("1000")) == "1.0k MXN"
    assert _format_mxn_thousands(Decimal("1555")) == "1.6k MXN"


def test_break_even_card_is_na_when_no_plan_charges_per_document(monkeypatch) -> None:
    monkeypatch.setattr(executive_dashboard, "_average_document_price", lambda repo, month: Decimal("0"))
    month = SeedRepository().available_months()[-1]

    content = str(_dashboard_content(month))

    assert "n/a" in content
    assert "No active plan charges per document" in content


def test_break_even_card_is_na_when_unit_price_does_not_cover_variable_cost(monkeypatch) -> None:
    repo = SeedRepository()
    month = repo.available_months()[-1]
    unit_variable_cost = repo.cost_rates(date.fromisoformat(f"{month}-01"))["saremi.document_validation"]
    assert unit_variable_cost > 0
    monkeypatch.setattr(
        executive_dashboard,
        "_average_document_price",
        lambda repo, month: unit_variable_cost / Decimal("2"),
    )

    content = str(_dashboard_content(month))

    assert "n/a" in content
    assert "Unit price does not cover variable cost" in content


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None:
            yield from _walk(child)


def test_summary_migrates_only_its_two_tables_and_exposes_all_chart_values():
    from dash import dash_table, dcc, html
    from dash_ag_grid import AgGrid

    content = _dashboard_content(SeedRepository().available_months()[-1])
    components = list(_walk(content))
    grids = [item for item in components if isinstance(item, AgGrid)]
    assert {grid.id for grid in grids} == {"top-clients", "low-margin-clients"}
    assert not any(isinstance(item, dash_table.DataTable) for item in components)
    assert len([item for item in components if isinstance(item, dcc.Tooltip)]) == 5
    assert len([item for item in components if isinstance(item, html.Details)]) == 5
    for grid in grids:
        assert len(grid.rowData) <= 5
        assert grid.dashGridOptions["paginationPageSize"] == 5
        for row in grid.rowData:
            assert all(isinstance(value, (int, float)) for key, value in row.items() if key != "client")
        assert grid.columnDefs[1]["filter"] == "agNumberColumnFilter"
        assert grid.columnDefs[-1]["valueFormatter"]["function"] == "valtehPercent(params)"


def test_empty_grid_retains_columns_and_empty_chart_has_accessible_state():
    from app.components.chart_shell import chart_with_tooltip
    from app.components.executive_visuals import client_grid

    grid = client_grid("empty", [])
    assert len(grid.columnDefs) == 6
    assert grid.rowData == []
    chart = chart_with_tooltip(
        "empty-chart", _executive_bar_chart({}, "Costs"), metric_label="Cost", value_formatter=str
    )
    assert "No data for this view" in str(chart)


def test_executive_graph_keeps_a_stable_height_during_responsive_updates():
    from app.components.chart_shell import chart_with_tooltip

    chart = chart_with_tooltip(
        "stable-chart",
        _executive_bar_chart({"SAREMI": Decimal("10")}, "Costs"),
        metric_label="Cost",
        value_formatter=str,
    )
    graph = chart.children[0]

    assert graph.responsive is True
    assert graph.style == {"height": "28rem", "minHeight": "28rem"}


def test_tooltip_handles_negative_zero_usd_and_long_labels_without_markup():
    from app.components.chart_shell import chart_with_tooltip

    label = "<script>alert(1)</script>" + "Long name " * 30
    figure = _executive_bar_chart({label: Decimal("-1234.56"), "Zero": Decimal("0")}, "Margin", "USD")
    assert list(figure.data[0].customdata) == ["$-1,234.56 USD", "$0.00 USD"]
    chart = chart_with_tooltip("margin", figure, metric_label="Margin", value_formatter=str)
    assert chart.children[0].clear_on_unhover is True
    first_term = next(component for component in _walk(chart.children[2]) if isinstance(component, html.Dt))
    assert first_term.children == label


def test_category_colors_remain_stable_across_order_and_chart_type():
    bar = _executive_bar_chart({"SAREMI": Decimal(1), "Graphos": Decimal(2)}, "Costs")
    pie = _executive_pie_chart({"Graphos": Decimal(2), "SAREMI": Decimal(1)}, "Revenue")
    assert bar.data[0].marker.color[0] == pie.data[0].marker.colors[1]
    assert bar.data[0].marker.color[1] == pie.data[0].marker.colors[0]


def test_tooltip_callbacks_run_clientside_and_invalidate_on_new_figures():
    from dash import Dash

    app = Dash(__name__, suppress_callback_exceptions=True)
    executive_dashboard.register_callbacks(app)
    callbacks = [item for item in app._callback_list if item.get("clientside_function")]
    assert len(callbacks) == 5
    for callback in callbacks:
        assert callback["clientside_function"] == {"namespace": "valtehCharts", "function_name": "tooltip"}
        assert [item["property"] for item in callback["inputs"]] == ["hoverData", "figure"]


def test_client_grid_values_preserve_existing_profitability_and_ranking():
    from types import SimpleNamespace

    class Repo:
        def monthly_summary(self, month):
            return {"fixed_cost": Decimal("100.00")}

        def active_clients(self, month):
            return [SimpleNamespace(id=1, name="Small"), SimpleNamespace(id=2, name="Large")]

        def client_profitability(self, client_id, month):
            revenue = Decimal("20.25") if client_id == 1 else Decimal("1000.75")
            return SimpleNamespace(
                revenue=revenue, variable_cost=Decimal("10.10"), gross_margin=revenue - Decimal("10.10")
            )

    rows = executive_dashboard._client_rows(Repo(), "2026-08")
    assert [row["client"] for row in rows] == ["Large", "Small"]
    assert rows[1]["revenue"] == 20.25
    assert rows[1]["allocated_fixed_cost"] == 50
    assert rows[1]["operating_margin"] == -39.85
    assert rows[1]["operating_margin_percentage"] == float(Decimal("-39.85") / Decimal("20.25"))


def test_explicit_theme_wins_over_previous_cookie():
    from flask import Flask

    from app.components.chart_theme import chart_colorway

    with Flask(__name__).test_request_context("/", environ_overrides={"HTTP_COOKIE": "valteh-theme=light"}):
        figure = _executive_bar_chart({"SAREMI": Decimal(10)}, "Costs", theme="dark")
    assert figure.data[0].marker.color[0] == chart_colorway("dark")[0]
