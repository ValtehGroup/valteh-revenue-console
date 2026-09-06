import plotly.graph_objects as go
from dash import Dash, dcc, html

from app.components.chart_shell import chart_with_tooltip, register_chart_tooltips


def test_chart_shell_has_stable_height_tooltip_and_accessible_exact_values() -> None:
    figure = go.Figure(go.Bar(x=["Zero", "Loss", "Missing"], y=[0, -12.5, None]))

    shell = chart_with_tooltip(
        "test-chart",
        figure,
        metric_label="Cost",
        value_formatter=lambda value: f"${float(value):,.2f} USD",
        height="24rem",
    )

    graph, tooltip, values = shell.children
    assert isinstance(graph, dcc.Graph)
    assert graph.style == {"height": "24rem", "minHeight": "24rem"}
    assert graph.figure.data[0].hoverinfo == "none"
    assert graph.figure.data[0].hovertemplate is None
    assert [row[3] for row in graph.figure.data[0].customdata] == ["$0.00 USD", "$-12.50 USD", "—"]
    assert isinstance(tooltip, dcc.Tooltip)
    assert isinstance(values, html.Details)
    assert "Zero" in str(values) and "$-12.50 USD" in str(values)


def test_tooltip_registration_is_clientside_and_uses_figure_to_clear_stale_content() -> None:
    app = Dash(__name__, suppress_callback_exceptions=True)

    register_chart_tooltips(app, ("first-chart", "second-chart"))

    assert len(app._callback_list) == 2
    for callback in app._callback_list:
        assert callback["clientside_function"] == {"namespace": "valtehCharts", "function_name": "tooltip"}
        assert [item["property"] for item in callback["inputs"]] == ["hoverData", "figure"]
