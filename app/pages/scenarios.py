from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dcc, html

from app.components.chart_theme import apply_chart_theme
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.scenario_forecast import ScenarioMonth, forecast_scenarios
from app.utils.currency import format_mxn, format_percent


def layout():
    repo = SeedRepository()
    forecast = forecast_scenarios(repo, horizon_months=6)
    latest_month = repo.available_months()[-1]
    return html.Div(
        [
            html.H1("Scenarios", className="h3"),
            html.P(
                "Six-month forecast comparing Base, Pessimistic, and Optimistic cases.",
                className="text-muted",
            ),
            _assumption_summary(latest_month),
            _scenario_kpis(forecast),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=_line_chart(forecast, "revenue", "Revenue Forecast")), md=6),
                    dbc.Col(dcc.Graph(figure=_line_chart(forecast, "total_cost", "Cost Forecast")), md=6),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=_line_chart(forecast, "operating_margin", "Operating Margin")), md=6),
                    dbc.Col(dcc.Graph(figure=_line_chart(forecast, "clients", "Active Clients")), md=6),
                ],
                className="mb-4",
            ),
            html.H2("Month-by-month Forecast", className="h5"),
            data_table("scenario-forecast-table", _table_rows(forecast), 18),
        ]
    )


def register_callbacks(app) -> None:
    return None


def _assumption_summary(latest_month: str) -> dbc.Alert:
    return dbc.Alert(
        [
            html.Strong(f"Forecast starts from {latest_month}. "),
            html.Span(
                "Base keeps current clients, revenue, and costs. Pessimistic increases fixed costs by 10%, "
                "variable costs by 20%, removes the largest client from month 2, and adds no clients. "
                "Optimistic reduces variable costs by 10% and adds one average new client from month 4."
            ),
        ],
        color="light",
        className="mb-4",
    )


def _scenario_kpis(forecast: list[ScenarioMonth]) -> dbc.Row:
    final_month = forecast[-1].month
    final_rows = [month for month in forecast if month.month == final_month]
    return dbc.Row(
        [
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(row.scenario, className="scenario-card-title small text-uppercase"),
                            html.Div(
                                [
                                    html.Span("Revenue"),
                                    html.Strong(format_mxn(row.revenue)),
                                ],
                                className="revenue-split-row",
                            ),
                            html.Div(
                                [
                                    html.Span("Total costs"),
                                    html.Strong(format_mxn(row.fixed_cost + row.variable_cost)),
                                ],
                                className="revenue-split-row",
                            ),
                            html.Div(f"{row.clients} clients in {final_month}", className="small text-muted mt-1"),
                        ]
                    ),
                    className=f"scenario-summary-card scenario-summary-{row.scenario.lower()} h-100",
                ),
                md=4,
            )
            for row in final_rows
        ],
        className="g-3 mb-4",
    )


def _line_chart(forecast: list[ScenarioMonth], metric: str, title: str):
    df = _forecast_frame(forecast)
    fig = px.line(df, x="month", y=metric, color="scenario", markers=True, title=title)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), xaxis_title="", legend_title="")
    if metric != "clients":
        fig.update_yaxes(title="MXN", tickprefix="$", separatethousands=True)
    else:
        fig.update_yaxes(title="Clients")
    return apply_chart_theme(fig)


def _forecast_frame(forecast: list[ScenarioMonth]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": month.scenario,
                "month": month.month,
                "clients": month.clients,
                "revenue": float(month.revenue),
                "fixed_cost": float(month.fixed_cost),
                "variable_cost": float(month.variable_cost),
                "total_cost": float(month.fixed_cost + month.variable_cost),
                "operating_margin": float(month.operating_margin),
            }
            for month in forecast
        ]
    )


def _table_rows(forecast: list[ScenarioMonth]) -> list[dict]:
    rows = []
    for month in forecast:
        total_cost = month.fixed_cost + month.variable_cost
        margin_pct = month.operating_margin / month.revenue if month.revenue else 0
        rows.append(
            {
                "scenario": month.scenario,
                "month": month.month,
                "clients": month.clients,
                "revenue": format_mxn(month.revenue),
                "fixed_cost": format_mxn(month.fixed_cost),
                "variable_cost": format_mxn(month.variable_cost),
                "total_cost": format_mxn(total_cost),
                "operating_margin": format_mxn(month.operating_margin),
                "margin_percentage": format_percent(margin_pct),
            }
        )
    return rows
