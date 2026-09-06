from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Input, Output, ctx, dcc, html, no_update

from app.components.chart_shell import chart_with_tooltip, prepare_chart_figure, register_chart_tooltips
from app.components.chart_theme import apply_chart_theme, stable_category_colors
from app.components.tables import data_grid
from app.config import get_settings
from app.data.fx_rate_repository import FxRateRepository
from app.data.repositories import SeedRepository
from app.domain.display_currency import format_currency, normalize_display_currency, translate_mxn, usd_view_note
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


def layout(display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    reference_rate = _latest_reference_rate()
    assumption_summary, scenario_results = _scenario_outputs(
        reference_rate,
        DEFAULT_DOWNSIDE_USD_MXN_CHANGE * Decimal("100"),
        DEFAULT_UPSIDE_USD_MXN_CHANGE * Decimal("100"),
        currency,
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
            usd_view_note(currency, scenario=True),
            html.Div(id="scenario-results", children=scenario_results),
        ]
    )


def register_callbacks(app) -> None:
    register_chart_tooltips(
        app,
        (
            "scenario-revenue-chart",
            "scenario-cost-chart",
            "scenario-margin-chart",
            "scenario-clients-chart",
            "scenario-fx-history-chart",
        ),
    )

    @app.callback(
        Output("scenario-assumption-summary", "children"),
        Output("scenario-results", "children"),
        Input("scenario-reference-usd-mxn-rate", "value"),
        Input("scenario-downside-usd-mxn-change", "value"),
        Input("scenario-upside-usd-mxn-change", "value"),
        Input("display-currency-store", "data"),
        Input("theme-store", "data"),
    )
    def update_scenarios(
        reference_usd_mxn_rate: float | str | None,
        downside_usd_mxn_change: float | str | None,
        upside_usd_mxn_change: float | str | None,
        display_currency: str | None,
        theme_data: dict | None,
    ):
        if None in (reference_usd_mxn_rate, downside_usd_mxn_change, upside_usd_mxn_change):
            return no_update, no_update
        try:
            return _scenario_outputs(
                reference_usd_mxn_rate,
                downside_usd_mxn_change,
                upside_usd_mxn_change,
                display_currency,
                theme=theme_data.get("theme") if isinstance(theme_data, dict) else None,
            )
        except ValueError as exc:
            return dbc.Alert(str(exc), color="danger", className="h-100 mb-0"), no_update

    @app.callback(
        Output("scenario-reference-usd-mxn-rate", "value"),
        Output("scenario-fx-update-status", "children"),
        Output("scenario-fx-latest", "children"),
        Output("scenario-fx-history-chart", "figure"),
        Input("scenario-fx-update", "n_clicks"),
        Input("theme-store", "data"),
        prevent_initial_call=True,
        running=[(Output("scenario-fx-update", "disabled"), True, False)],
    )
    def update_fx_history(_n_clicks: int | None, theme_data: dict | None):
        theme = theme_data.get("theme") if isinstance(theme_data, dict) else None
        if ctx.triggered_id == "theme-store":
            repository = FxRateRepository()
            status = repository.status()
            observations = _recent_fx_observations(repository, status.latest)
            return no_update, no_update, no_update, _fx_history_figure(observations, theme)
        return _update_fx_history(theme=theme)


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
                    chart_with_tooltip(
                        "scenario-fx-history-chart",
                        _fx_history_figure(observations),
                        metric_label="MXN per USD",
                        value_formatter=lambda value: f"{float(value):,.4f}",
                        height="20rem",
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
    *,
    theme: str | None = None,
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
        _fx_history_figure(observations, theme),
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


def _fx_history_figure(observations: list[FxRateObservation], theme: str | None = None):
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
    figure.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20), xaxis_title="")
    figure.update_yaxes(title="MXN per USD", tickformat=".4f")
    return prepare_chart_figure(
        apply_chart_theme(figure, theme),
        "MXN per USD",
        lambda value: f"{float(value):,.4f}",
    )


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
    display_currency: str | None = "MXN",
    *,
    theme: str | None = None,
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
    return _assumption_summary(latest_month, forecast), _scenario_results(forecast, display_currency, theme=theme)


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


def _scenario_results(
    forecast: list[ScenarioMonth],
    display_currency: str | None = "MXN",
    *,
    theme: str | None = None,
) -> html.Div:
    currency = normalize_display_currency(display_currency)
    return html.Div(
        [
            _scenario_kpis(forecast, currency),
            dbc.Row(
                [
                    dbc.Col(
                        chart_with_tooltip(
                            "scenario-revenue-chart",
                            _line_chart(forecast, "revenue", "Revenue Forecast", currency, theme),
                            metric_label="Revenue",
                            value_formatter=lambda value: format_currency(value, currency, decimals=2),
                            series=True,
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        chart_with_tooltip(
                            "scenario-cost-chart",
                            _line_chart(forecast, "total_cost", "Cost Forecast", currency, theme),
                            metric_label="Total cost",
                            value_formatter=lambda value: format_currency(value, currency, decimals=2),
                            series=True,
                        ),
                        md=6,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        chart_with_tooltip(
                            "scenario-margin-chart",
                            _line_chart(forecast, "operating_margin", "Operating Margin", currency, theme),
                            metric_label="Operating margin",
                            value_formatter=lambda value: format_currency(value, currency, decimals=2),
                            series=True,
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        chart_with_tooltip(
                            "scenario-clients-chart",
                            _line_chart(forecast, "clients", "Active Clients", theme=theme),
                            metric_label="Active clients",
                            value_formatter=lambda value: f"{int(value):,}",
                            series=True,
                        ),
                        md=6,
                    ),
                ],
                className="mb-4",
            ),
            html.H2("Month-by-month Forecast", className="h5"),
            data_grid(
                "scenario-forecast-table",
                _table_rows(forecast),
                18,
                column_options={"usd_mxn_rate": {"name": "USD/MXN"}},
                pagination=False,
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


def _scenario_kpis(forecast: list[ScenarioMonth], display_currency: str = "MXN") -> dbc.Row:
    currency = normalize_display_currency(display_currency)
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
                                    html.Strong(
                                        format_currency(
                                            translate_mxn(row.revenue, currency, row.usd_mxn_rate), currency
                                        )
                                    ),
                                ],
                                className="revenue-split-row",
                            ),
                            html.Div(
                                [
                                    html.Span("Total costs"),
                                    html.Strong(
                                        format_currency(
                                            translate_mxn(
                                                row.fixed_cost + row.variable_cost,
                                                currency,
                                                row.usd_mxn_rate,
                                            ),
                                            currency,
                                        )
                                    ),
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


def _line_chart(
    forecast: list[ScenarioMonth],
    metric: str,
    title: str,
    display_currency: str = "MXN",
    theme: str | None = None,
):
    currency = normalize_display_currency(display_currency)
    df = _forecast_frame(forecast, currency)
    fig = px.line(
        df,
        x="month",
        y=metric,
        color="scenario",
        markers=True,
        title=title,
        color_discrete_map=stable_category_colors(df["scenario"].unique(), theme),
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), xaxis_title="", legend_title="")
    if metric != "clients":
        fig.update_yaxes(title=currency, tickprefix="$", separatethousands=True)
    else:
        fig.update_yaxes(title="Clients")
    return apply_chart_theme(fig, theme)


def _forecast_frame(forecast: list[ScenarioMonth], display_currency: str = "MXN") -> pd.DataFrame:
    currency = normalize_display_currency(display_currency)
    return pd.DataFrame(
        [
            {
                "scenario": month.scenario,
                "month": month.month,
                "clients": month.clients,
                "revenue": float(translate_mxn(month.revenue, currency, month.usd_mxn_rate)),
                "fixed_cost": float(translate_mxn(month.fixed_cost, currency, month.usd_mxn_rate)),
                "variable_cost": float(translate_mxn(month.variable_cost, currency, month.usd_mxn_rate)),
                "total_cost": float(
                    translate_mxn(month.fixed_cost + month.variable_cost, currency, month.usd_mxn_rate)
                ),
                "operating_margin": float(translate_mxn(month.operating_margin, currency, month.usd_mxn_rate)),
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
                "usd_mxn_rate": float(month.usd_mxn_rate),
                "clients": month.clients,
                "revenue": float(month.revenue),
                "fixed_cost": float(month.fixed_cost),
                "variable_cost": float(month.variable_cost),
                "total_cost": float(total_cost),
                "operating_margin": float(month.operating_margin),
                "margin_percentage": float(margin_pct),
            }
        )
    return rows
