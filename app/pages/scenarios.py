from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html, no_update

from app.components.chart_theme import apply_chart_theme
from app.components.tables import data_table
from app.config import get_settings
from app.data.fx_rate_repository import FxRateRepository
from app.data.repositories import SeedRepository
from app.domain.fx_history_sync import FxHistorySyncService
from app.domain.fx_rates import FxRateObservation
from app.domain.scenario_forecast import (
    DEFAULT_DOWNSIDE_USD_MXN_CHANGE,
    DEFAULT_REFERENCE_USD_MXN_RATE,
    DEFAULT_UPSIDE_USD_MXN_CHANGE,
    ScenarioMonth,
    forecast_scenarios,
)
from app.integrations.banxico_sie_api import BanxicoSIEAPIError, BanxicoSIEClient
from app.utils.currency import format_mxn, format_percent


def layout():
    reference_rate = _latest_reference_rate()
    assumption_summary, scenario_results = _scenario_outputs(
        reference_rate,
        DEFAULT_DOWNSIDE_USD_MXN_CHANGE * Decimal("100"),
        DEFAULT_UPSIDE_USD_MXN_CHANGE * Decimal("100"),
    )
    return html.Div(
        [
            html.H1("Scenarios", className="h3"),
            html.P(
                "Six-month forecast comparing Base, Pessimistic, and Optimistic cases.",
                className="text-muted",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(id="scenario-assumption-summary", children=assumption_summary, className="h-100"),
                        lg=7,
                    ),
                    dbc.Col(_exchange_rate_controls(reference_rate), lg=5),
                ],
                className="g-3 mb-4 align-items-stretch",
            ),
            _fx_history_panel(),
            html.Div(id="scenario-results", children=scenario_results),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("scenario-assumption-summary", "children"),
        Output("scenario-results", "children"),
        Input("scenario-reference-usd-mxn-rate", "value"),
        Input("scenario-downside-usd-mxn-change", "value"),
        Input("scenario-upside-usd-mxn-change", "value"),
    )
    def update_scenarios(
        reference_usd_mxn_rate: float | str | None,
        downside_usd_mxn_change: float | str | None,
        upside_usd_mxn_change: float | str | None,
    ):
        if None in (reference_usd_mxn_rate, downside_usd_mxn_change, upside_usd_mxn_change):
            return no_update, no_update
        try:
            return _scenario_outputs(
                reference_usd_mxn_rate,
                downside_usd_mxn_change,
                upside_usd_mxn_change,
            )
        except ValueError as exc:
            return dbc.Alert(str(exc), color="danger", className="h-100 mb-0"), no_update

    @app.callback(
        Output("scenario-reference-usd-mxn-rate", "value"),
        Output("scenario-fx-update-status", "children"),
        Output("scenario-fx-latest", "children"),
        Output("scenario-fx-history-chart", "figure"),
        Input("scenario-fx-update", "n_clicks"),
        prevent_initial_call=True,
        running=[(Output("scenario-fx-update", "disabled"), True, False)],
    )
    def update_fx_history(_n_clicks: int | None):
        return _update_fx_history()


def _exchange_rate_controls(reference_rate: Decimal = DEFAULT_REFERENCE_USD_MXN_RATE) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    _scenario_input(
                        "Baseline USD:MXN",
                        "scenario-reference-usd-mxn-rate",
                        float(reference_rate),
                        min_value=0.01,
                        step=0.01,
                    ),
                    _scenario_input(
                        "Downside %",
                        "scenario-downside-usd-mxn-change",
                        float(DEFAULT_DOWNSIDE_USD_MXN_CHANGE * Decimal("100")),
                        min_value=-99.99,
                        step=0.1,
                    ),
                    _scenario_input(
                        "Upside %",
                        "scenario-upside-usd-mxn-change",
                        float(DEFAULT_UPSIDE_USD_MXN_CHANGE * Decimal("100")),
                        min_value=-99.99,
                        step=0.1,
                    ),
                ],
                className="g-2",
            )
        ),
        className="content-card h-100",
    )


def _latest_reference_rate(repository: FxRateRepository | None = None) -> Decimal:
    latest = (repository or FxRateRepository()).latest()
    return latest.rate if latest is not None else DEFAULT_REFERENCE_USD_MXN_RATE


def _fx_history_panel(repository: FxRateRepository | None = None) -> dbc.Card:
    repo = repository or FxRateRepository()
    status = repo.status()
    token_configured = get_settings().banxico_sie_token is not None
    observations = _recent_fx_observations(repo, status.latest)
    return dbc.Card(
        dbc.CardBody(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H2("USD/MXN FIX history", className="h5 mb-1"),
                                html.Div(
                                    _latest_fx_label(status.latest),
                                    id="scenario-fx-latest",
                                    className="small text-muted",
                                ),
                            ],
                            width=True,
                        ),
                        dbc.Col(
                            dbc.Button(
                                "Update FX history",
                                id="scenario-fx-update",
                                color="primary",
                                disabled=not token_configured,
                            ),
                            width="auto",
                        ),
                    ],
                    className="align-items-center g-2",
                ),
                html.Div(
                    "" if token_configured else "Banxico SIE token is not configured.",
                    id="scenario-fx-update-status",
                    className="small text-muted mt-1",
                ),
                dcc.Loading(
                    dcc.Graph(
                        id="scenario-fx-history-chart",
                        figure=_fx_history_figure(observations),
                        config={"displaylogo": False},
                    ),
                    type="circle",
                ),
            ]
        ),
        className="content-card mb-4",
    )


def _update_fx_history(
    repository: FxRateRepository | None = None,
    client: BanxicoSIEClient | None = None,
):
    repo = repository or FxRateRepository()
    if client is None:
        token = get_settings().banxico_sie_token
        if token is None:
            return (
                no_update,
                _fx_status_message("Banxico SIE token is not configured.", error=True),
                no_update,
                no_update,
            )
        client = BanxicoSIEClient(token.get_secret_value())
    try:
        result = FxHistorySyncService(client, repo).sync()
    except (BanxicoSIEAPIError, ValueError, RuntimeError) as exc:
        return no_update, _fx_status_message(str(exc), error=True), no_update, no_update
    except Exception:
        return no_update, _fx_status_message("FX history update failed.", error=True), no_update, no_update

    observations = _recent_fx_observations(repo, result.latest)
    message = (
        f"Updated through {result.latest.rate_date.isoformat()}: "
        f"{result.inserted} inserted, {result.updated} refreshed."
    )
    return (
        format(result.latest.rate, "f"),
        _fx_status_message(message),
        _latest_fx_label(result.latest),
        _fx_history_figure(observations),
    )


def _recent_fx_observations(
    repository: FxRateRepository,
    latest: FxRateObservation | None,
) -> list[FxRateObservation]:
    if latest is None:
        return []
    return repository.observations(latest.rate_date - timedelta(days=365), latest.rate_date)


def _latest_fx_label(latest: FxRateObservation | None) -> str:
    if latest is None:
        return "No stored FIX rate"
    return f"Latest FIX {latest.rate:.4f} · {latest.rate_date.isoformat()}"


def _fx_status_message(message: str, *, error: bool = False) -> html.Span:
    return html.Span(message, className=f"small {'text-danger' if error else 'text-success'}")


def _fx_history_figure(observations: list[FxRateObservation]):
    if not observations:
        figure = px.line(title="USD/MXN FIX")
        figure.add_annotation(text="No FX history stored", showarrow=False)
    else:
        frame = pd.DataFrame(
            {
                "date": [row.rate_date for row in observations],
                "rate": [float(row.rate) for row in observations],
            }
        )
        figure = px.line(frame, x="date", y="rate", title="USD/MXN FIX")
        figure.update_traces(hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}<extra></extra>")
    figure.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20), xaxis_title="")
    figure.update_yaxes(title="MXN per USD", tickformat=".4f")
    return apply_chart_theme(figure)


def _scenario_input(
    label: str,
    component_id: str,
    value: float,
    *,
    min_value: float,
    step: float,
) -> dbc.Col:
    input_component = dcc.Input(
        id=component_id,
        type="text",
        inputMode="numeric",
        value=value,
        min=min_value,
        step=step,
        debounce=False,
        className="form-control",
    )
    return dbc.Col(
        [
            dbc.Label(label, html_for=component_id, className="small mb-1"),
            input_component,
        ],
        md=4,
    )


def _scenario_outputs(
    reference_usd_mxn_rate: Decimal | float | int | str | None,
    downside_usd_mxn_change: Decimal | float | int | str | None,
    upside_usd_mxn_change: Decimal | float | int | str | None,
):
    reference_rate = _positive_decimal(reference_usd_mxn_rate, "Baseline USD:MXN")
    downside_change = _percentage_change(downside_usd_mxn_change, "Downside change")
    upside_change = _percentage_change(upside_usd_mxn_change, "Upside change")

    repo = SeedRepository()
    latest_month = repo.available_months()[-1]
    forecast = forecast_scenarios(
        repo,
        horizon_months=6,
        reference_usd_mxn_rate=reference_rate,
        scenario_usd_mxn_changes={
            "Pessimistic": downside_change,
            "Optimistic": upside_change,
        },
    )
    return _assumption_summary(latest_month, forecast), _scenario_results(forecast)


def _positive_decimal(value: Decimal | float | int | str | None, label: str) -> Decimal:
    number = _decimal(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return number


def _percentage_change(value: Decimal | float | int | str | None, label: str) -> Decimal:
    percentage = _decimal(value, label)
    if percentage <= Decimal("-100"):
        raise ValueError(f"{label} must be greater than -100%.")
    return percentage / Decimal("100")


def _decimal(value: Decimal | float | int | str | None, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Enter a valid value for {label}.") from exc
    if not number.is_finite():
        raise ValueError(f"Enter a valid value for {label}.")
    return number


def _scenario_results(forecast: list[ScenarioMonth]) -> html.Div:
    return html.Div(
        [
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
            data_table(
                "scenario-forecast-table",
                _table_rows(forecast),
                18,
                column_options={"usd_mxn_rate": {"name": "USD/MXN"}},
            ),
        ]
    )


def _assumption_summary(latest_month: str, forecast: list[ScenarioMonth]) -> dbc.Alert:
    scenario_rates = {}
    for month in forecast:
        scenario_rates.setdefault(month.scenario, month.usd_mxn_rate)
    rate_summary = ", ".join(f"{name} {rate:.2f}" for name, rate in scenario_rates.items())
    return dbc.Alert(
        [
            html.Strong(f"Forecast starts from {latest_month}. "),
            html.Span(
                "Base keeps current clients, revenue, and costs. Pessimistic increases fixed costs by 10%, "
                "variable costs by 20%, removes the largest client from month 2, and adds no clients. "
                "Optimistic reduces variable costs by 10% and adds one average new client from month 4. "
                f"USD/MXN assumptions (MXN per USD): {rate_summary}."
            ),
        ],
        color="light",
        className="h-100 mb-0",
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
                "usd_mxn_rate": f"{month.usd_mxn_rate:.2f}",
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
