"""Shared Plotly presentation shell with rich, accessible tooltips."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from math import isnan
from typing import Any

import plotly.graph_objects as go
from dash import ClientsideFunction, Input, Output, dcc, html

DEFAULT_CHART_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": "reset",
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}


def chart_with_tooltip(
    chart_id: str,
    figure: go.Figure,
    *,
    metric_label: str,
    value_formatter: Callable[[Any], str],
    series: bool = False,
    height: str = "28rem",
    config: dict[str, Any] | None = None,
    empty_message: str = "No data for this view",
    context_by_category: dict[str, str] | None = None,
    class_name: str = "",
) -> html.Div:
    """Render a responsive graph and attach uniform tooltip metadata to its points."""
    prepared = prepare_chart_figure(
        figure,
        metric_label,
        value_formatter,
        series=series,
        context_by_category=context_by_category,
    )
    graph_config = {**DEFAULT_CHART_CONFIG, **(config or {})}
    return html.Div(
        [
            dcc.Graph(
                id=chart_id,
                figure=prepared,
                clear_on_unhover=True,
                responsive=True,
                config=graph_config,
                style={"height": height, "minHeight": height},
            ),
            dcc.Tooltip(
                id=f"{chart_id}-tooltip",
                className="chart-tooltip",
                background_color="var(--color-surface)",
                border_color="var(--color-border)",
                loading_text="",
                zindex=1000,
            ),
            html.Details(
                [
                    html.Summary("View exact values"),
                    html.Div(id=f"{chart_id}-values", children=_value_rows(prepared, empty_message)),
                ],
                className="chart-values",
            ),
        ],
        className=" ".join(part for part in ("chart-shell", class_name) if part),
    )


def prepare_chart_figure(
    figure: go.Figure,
    metric_label: str,
    value_formatter: Callable[[Any], str],
    *,
    series: bool = False,
    context_by_category: dict[str, str] | None = None,
) -> go.Figure:
    """Store safe display metadata on each point and disable Plotly's native hover."""
    for trace in figure.data:
        values = _trace_values(trace)
        categories = _trace_categories(trace)
        point_count = min(len(values), len(categories))
        trace_name = str(trace.name or "")
        metadata = []
        for index in range(point_count):
            category = str(categories[index])
            title = trace_name if series and trace_name else category
            context = category if series and trace_name else (context_by_category or {}).get(category, "")
            metadata.append([title, context, metric_label, _format_value(values[index], value_formatter)])
        trace.customdata = metadata
        trace.hoverinfo = "none"
        trace.hovertemplate = None
    return figure


def register_chart_tooltips(app, chart_ids: Iterable[str]) -> None:
    for chart_id in chart_ids:
        app.clientside_callback(
            ClientsideFunction(namespace="valtehCharts", function_name="tooltip"),
            Output(f"{chart_id}-tooltip", "show"),
            Output(f"{chart_id}-tooltip", "bbox"),
            Output(f"{chart_id}-tooltip", "children"),
            Output(f"{chart_id}-tooltip", "direction"),
            Output(f"{chart_id}-values", "children"),
            Input(chart_id, "hoverData"),
            Input(chart_id, "figure"),
        )


def _trace_values(trace) -> list[Any]:
    values = trace.values if getattr(trace, "type", None) in {"pie", "funnelarea"} else trace.y
    return list(values) if values is not None else []


def _trace_categories(trace) -> list[Any]:
    categories = trace.labels if getattr(trace, "type", None) in {"pie", "funnelarea"} else trace.x
    return list(categories) if categories is not None else []


def _format_value(value: Any, formatter: Callable[[Any], str]) -> str:
    if value is None:
        return "—"
    try:
        if isnan(float(value)):
            return "—"
    except (TypeError, ValueError):
        pass
    return formatter(value)


def _value_rows(figure: go.Figure, empty_message: str):
    rows = [
        metadata for trace in figure.data for metadata in (trace.customdata if trace.customdata is not None else [])
    ]
    if not rows:
        return html.Div(empty_message, className="chart-empty-value")
    return html.Dl(
        [
            html.Div(
                [
                    html.Dt(" · ".join(part for part in (str(row[0]), str(row[1])) if part)),
                    html.Dd(str(row[3])),
                ],
                className="chart-value-row",
            )
            for row in rows
        ]
    )
