from decimal import Decimal

import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, dcc, html

from app.components.charts import bar_chart, pie_chart
from app.components.filters import month_filter
from app.components.kpi_card import kpi_card
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.display_currency import (
    format_compact_currency,
    format_currency,
    normalize_display_currency,
    translate_mxn,
    usd_view_note,
)
from app.domain.fx_rates import FxRateUnavailableError
from app.domain.revenue_engine import monthly_revenue_recognition_date
from app.domain.unit_economics import calculate_break_even_usage, money
from app.utils.currency import format_mxn, format_percent


def layout(display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    latest_month = SeedRepository().available_months()[-1]
    return html.Div(
        [
            html.Div(
                [
                    html.H1("Executive Summary", className="h3"),
                    html.P("Monthly economics overview", className="text-muted"),
                ]
            ),
            dbc.Row([month_filter("executive-month-filter", latest_month)], className="mb-3"),
            html.Div(id="executive-dashboard-content", children=_dashboard_content(latest_month, currency)),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("executive-dashboard-content", "children"),
        Input("executive-month-filter", "value"),
        Input("display-currency-store", "data"),
    )
    def update_dashboard(month: str, display_currency: str | None):
        try:
            return _dashboard_content(month, display_currency)
        except FxRateUnavailableError as exc:
            return dbc.Alert(str(exc), color="danger")

    @app.callback(
        Output("executive-monthly-revenue-dynamic", "children"),
        Input("executive-monthly-revenue", "n_clicks"),
        State("executive-month-filter", "value"),
        State("display-currency-store", "data"),
    )
    def toggle_revenue_card(n_clicks: int | None, month: str, display_currency: str | None):
        return _monthly_revenue_card_content(
            month,
            show_split=bool(n_clicks and n_clicks % 2),
            display_currency=display_currency,
        )


def _dashboard_content(month: str, display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    repo = SeedRepository()
    presentation = repo.monthly_presentation(month, currency)
    summary = presentation["summary"]
    revenue_by_service = presentation["revenue_by_service"]
    cost_by_service = presentation["cost_by_service"]
    cost_by_provider = presentation["cost_by_provider"]
    cost_by_category = presentation["cost_by_category"]
    variable_cost = summary["variable_cost"]
    revenue = summary["revenue"]
    operating_margin_pct = (summary["operating_margin"] / revenue) if revenue else Decimal("0")
    unit_price = _average_document_price(repo, month)
    unit_variable_cost = repo.cost_rates(pd.Timestamp(f"{month}-01").date()).get(
        "saremi.document_validation",
        Decimal("0"),
    )
    fixed_cost_mxn = sum(
        (amount.amount for amount, _ in presentation["translated_costs"] if amount.cost_type == "fixed"),
        Decimal("0"),
    )
    if unit_price <= 0:
        break_even_usage = None
        break_even_note = "No active plan charges per document"
    elif unit_price <= unit_variable_cost:
        break_even_usage = None
        break_even_note = "Unit price does not cover variable cost"
    else:
        break_even_usage = calculate_break_even_usage(fixed_cost_mxn, unit_price, unit_variable_cost)
        display_unit_price = unit_price
        display_unit_variable_cost = unit_variable_cost
        if currency == "USD":
            recognition_date, _ = monthly_revenue_recognition_date(pd.Timestamp(f"{month}-01").date())
            unit_rate = repo.usd_mxn_rates_for_dates([recognition_date])[recognition_date]
            display_unit_price = translate_mxn(unit_price, currency, unit_rate)
            display_unit_variable_cost = translate_mxn(unit_variable_cost, currency, unit_rate)
        break_even_note = (
            f"At {format_currency(display_unit_price, currency)} price and "
            f"{format_currency(display_unit_variable_cost, currency)} unit cost"
        )
    client_rows = _client_rows(repo, month)
    lowest_margin_rows = sorted(client_rows, key=lambda row: row["operating_margin_percentage"])[:5]

    return html.Div(
        [
            usd_view_note(currency),
            dbc.Row(
                [
                    dbc.Col(
                        _monthly_revenue_card(month, currency),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Fixed Costs",
                            format_currency(summary["fixed_cost"], currency),
                            color="secondary",
                            tooltip="Monthly active fixed costs, independent of usage volume.",
                            card_id="executive-fixed-costs",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Variable Costs",
                            format_currency(variable_cost, currency),
                            color="warning",
                            tooltip="Usage-driven costs: sum of each usage event quantity multiplied by its unit cost.",
                            card_id="executive-variable-costs",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Operating Margin",
                            format_percent(operating_margin_pct),
                            color="success" if operating_margin_pct > 0 else "danger",
                            tooltip="Operating margin percentage: revenue minus variable and fixed costs, "
                            "divided by revenue.",
                            card_id="executive-operating-margin",
                        ),
                        md=3,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        kpi_card(
                            "Burn Rate",
                            format_currency(summary["burn_rate"], currency),
                            color="danger",
                            tooltip="Cash consumed in the month when operating margin is negative; zero if profitable.",
                            card_id="executive-burn-rate",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Break-even Usage",
                            f"{break_even_usage:,} docs" if break_even_usage is not None else "n/a",
                            break_even_note,
                            tooltip="Documents needed to cover fixed costs: fixed costs divided by unit "
                            "contribution margin.",
                            card_id="executive-break-even-usage",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Active Clients",
                            str(len(repo.active_clients(month))),
                            tooltip="Clients with an active subscription during the selected month.",
                            card_id="executive-active-clients",
                        ),
                        md=3,
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(
                            figure=_executive_pie_chart(
                                revenue_by_service,
                                "Revenue by Service Line",
                                currency,
                            )
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dcc.Graph(
                            figure=_executive_bar_chart(
                                cost_by_service,
                                "Cost by Service Line",
                                currency,
                            )
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dcc.Graph(
                            figure=_executive_bar_chart(
                                _margin_by_service(revenue_by_service, cost_by_service),
                                "Margin by Service Line",
                                currency,
                            )
                        ),
                        md=4,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(
                            figure=_executive_bar_chart(
                                cost_by_provider,
                                "Costs by Provider",
                                currency,
                            )
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        dcc.Graph(
                            figure=_executive_bar_chart(
                                cost_by_category,
                                "Costs by Category",
                                currency,
                            )
                        ),
                        md=6,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2("Top Clients by Revenue", className="h5"),
                            data_table("top-clients", _display_rows(client_rows[:5]), 5),
                        ],
                        md=6,
                    ),
                    dbc.Col(
                        [
                            html.H2("Lowest-margin Clients", className="h5"),
                            data_table("low-margin-clients", _display_rows(lowest_margin_rows), 5),
                        ],
                        md=6,
                    ),
                ]
            ),
        ]
    )


def _client_rows(repo: SeedRepository, month: str) -> list[dict]:
    rows = []
    fixed_cost = repo.monthly_summary(month)["fixed_cost"]
    active_client_count = len(repo.active_clients(month))
    allocated_fixed_cost = fixed_cost / Decimal(active_client_count) if active_client_count else Decimal("0")
    for client in repo.active_clients(month):
        profitability = repo.client_profitability(client.id, month)
        operating_margin = profitability.gross_margin - allocated_fixed_cost
        operating_margin_percentage = operating_margin / money(profitability.revenue) if profitability.revenue else 0
        rows.append(
            {
                "client": client.name,
                "revenue": format_mxn(profitability.revenue),
                "revenue_value": float(profitability.revenue),
                "variable_cost": format_mxn(profitability.variable_cost),
                "allocated_fixed_cost": format_mxn(allocated_fixed_cost),
                "operating_margin": format_mxn(operating_margin),
                "operating_margin_percentage": float(operating_margin_percentage),
            }
        )
    return sorted(rows, key=lambda row: row["revenue_value"], reverse=True)


def _monthly_revenue_card(month: str, display_currency: str = "MXN") -> html.Div:
    tooltip = (
        "Total revenue recognized in the selected month. Click to split it into fixed subscription revenue "
        "and variable usage revenue."
    )
    return html.Div(
        [
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(
                            _monthly_revenue_card_content(month, show_split=False, display_currency=display_currency),
                            id="executive-monthly-revenue-dynamic",
                        ),
                    ],
                ),
                className="kpi-card h-100",
            ),
            html.Div(tooltip, className="kpi-tooltip", id="executive-monthly-revenue-tooltip", role="tooltip"),
        ],
        className="kpi-card-wrapper revenue-card-toggle h-100",
        id="executive-monthly-revenue",
        n_clicks=0,
        tabIndex=0,
        role="button",
        **{"aria-describedby": "executive-monthly-revenue-tooltip"},
    )


def _monthly_revenue_card_content(
    month: str,
    show_split: bool,
    display_currency: str | None = "MXN",
) -> list:
    currency = normalize_display_currency(display_currency)
    repo = SeedRepository()
    presentation = repo.monthly_presentation(month, currency)
    split = presentation["revenue_by_type"]
    split["total"] = presentation["summary"]["revenue"]
    split.setdefault("subscription", Decimal("0"))
    split.setdefault("usage", Decimal("0"))
    if show_split:
        return [
            html.Div("Monthly Revenue Split", className="kpi-label"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Subscription (fixed)", className="text-muted"),
                            html.Strong(format_currency(split["subscription"], currency)),
                        ],
                        className="revenue-split-row",
                    ),
                    html.Div(
                        [
                            html.Span("Usage (variable)", className="text-muted"),
                            html.Strong(format_currency(split["usage"], currency)),
                        ],
                        className="revenue-split-row",
                    ),
                ],
                className="mb-1",
            ),
            html.Div("Click to return to total", className="kpi-subtitle"),
        ]
    return [
        html.Div("Monthly Revenue", className="kpi-label"),
        html.Div(format_currency(split["total"], currency), className="kpi-value"),
        html.Div("Click for fixed / variable split", className="kpi-subtitle"),
    ]


def _display_rows(rows: list[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if key != "revenue_value"} for row in rows]


def _executive_bar_chart(data: dict[str, Decimal], title: str, display_currency: str = "MXN"):
    currency = normalize_display_currency(display_currency)
    figure = bar_chart(data, title, default_plotly_colors=True)
    figure.update_traces(
        customdata=[format_compact_currency(value, currency) for value in data.values()],
        hovertemplate="%{x}<br>%{customdata}<extra></extra>",
    )
    figure.update_yaxes(title=currency, tickformat=",.0f")
    return figure


def _executive_pie_chart(data: dict[str, Decimal], title: str, display_currency: str = "MXN"):
    currency = normalize_display_currency(display_currency)
    figure = pie_chart(data, title, default_plotly_colors=True)
    figure.update_traces(
        customdata=[format_compact_currency(value, currency) for value in data.values()],
        hovertemplate="%{label}<br>%{customdata}<extra></extra>",
    )
    return figure


def _format_mxn_thousands(value: Decimal) -> str:
    return format_compact_currency(value, "MXN").removeprefix("$")


def _average_document_price(repo: SeedRepository, month: str) -> Decimal:
    active_plans = [repo.active_plan_for_client_month(client.id, month) for client in repo.active_clients(month)]
    document_prices = [
        Decimal(str(plan.price_per_document)) for plan in active_plans if plan and plan.price_per_document > 0
    ]
    if not document_prices:
        document_prices = [
            Decimal(str(plan.price_per_document)) for plan in repo.pricing_plans() if plan.price_per_document > 0
        ]
    if not document_prices:
        return Decimal("0")
    return sum(document_prices, Decimal("0")) / Decimal(len(document_prices))


def _margin_by_service(revenue: dict[str, Decimal], costs: dict[str, Decimal]) -> dict[str, Decimal]:
    return {service: amount - costs.get(service, Decimal("0")) for service, amount in revenue.items()}
