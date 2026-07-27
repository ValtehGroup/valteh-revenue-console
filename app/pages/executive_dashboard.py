from decimal import Decimal

import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, dcc, html

from app.components.charts import bar_chart, pie_chart
from app.components.filters import month_filter
from app.components.kpi_card import kpi_card
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.unit_economics import calculate_break_even_usage, money
from app.utils.currency import format_mxn, format_percent


def layout():
    latest_month = SeedRepository().available_months()[-1]
    return html.Div(
        [
            html.Div(
                [
                    html.H1("Executive Dashboard", className="h3"),
                    html.P("Monthly economics overview", className="text-muted"),
                ]
            ),
            dbc.Row([month_filter("executive-month-filter", latest_month)], className="mb-3"),
            html.Div(id="executive-dashboard-content", children=_dashboard_content(latest_month)),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("executive-dashboard-content", "children"),
        Input("executive-month-filter", "value"),
    )
    def update_dashboard(month: str):
        return _dashboard_content(month)

    @app.callback(
        Output("executive-monthly-revenue-dynamic", "children"),
        Input("executive-monthly-revenue", "n_clicks"),
        State("executive-month-filter", "value"),
    )
    def toggle_revenue_card(n_clicks: int | None, month: str):
        return _monthly_revenue_card_content(month, show_split=bool(n_clicks and n_clicks % 2))


def _dashboard_content(month: str):
    repo = SeedRepository()
    summary = repo.monthly_summary(month)
    revenue_by_service = repo.revenue_by_service(month)
    cost_by_service = repo.cost_by_service(month)
    cost_by_provider = repo.cost_by_provider(month)
    cost_by_category = repo.cost_by_category(month)
    variable_cost = summary["variable_cost"]
    revenue = summary["revenue"]
    operating_margin_pct = (summary["operating_margin"] / revenue) if revenue else Decimal("0")
    unit_price = _average_document_price(repo, month)
    unit_variable_cost = repo.cost_rates(pd.Timestamp(f"{month}-01").date()).get(
        "saremi.document_validation",
        Decimal("0"),
    )
    break_even_usage = calculate_break_even_usage(summary["fixed_cost"], unit_price, unit_variable_cost)
    client_rows = _client_rows(repo, month)
    lowest_margin_rows = sorted(client_rows, key=lambda row: row["operating_margin_percentage"])[:5]

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        _monthly_revenue_card(month),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Fixed Costs",
                            format_mxn(summary["fixed_cost"]),
                            color="secondary",
                            tooltip="Monthly active fixed costs, independent of usage volume.",
                            card_id="executive-fixed-costs",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Variable Costs",
                            format_mxn(variable_cost),
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
                            format_mxn(summary["burn_rate"]),
                            color="danger",
                            tooltip="Cash consumed in the month when operating margin is negative; zero if profitable.",
                            card_id="executive-burn-rate",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Break-even Usage",
                            f"{break_even_usage:,} docs",
                            f"At {format_mxn(unit_price)} price and {format_mxn(unit_variable_cost)} unit cost",
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
                    dbc.Col(dcc.Graph(figure=pie_chart(revenue_by_service, "Revenue by Service Line")), md=4),
                    dbc.Col(dcc.Graph(figure=bar_chart(cost_by_service, "Cost by Service Line")), md=4),
                    dbc.Col(
                        dcc.Graph(
                            figure=bar_chart(
                                _margin_by_service(revenue_by_service, cost_by_service),
                                "Margin by Service Line",
                            )
                        ),
                        md=4,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=bar_chart(cost_by_provider, "Costs by Provider")), md=6),
                    dbc.Col(dcc.Graph(figure=bar_chart(cost_by_category, "Costs by Category")), md=6),
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


def _monthly_revenue_card(month: str) -> html.Div:
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
                            _monthly_revenue_card_content(month, show_split=False),
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


def _monthly_revenue_card_content(month: str, show_split: bool) -> list:
    repo = SeedRepository()
    split = repo.monthly_revenue_split(month)
    if show_split:
        return [
            html.Div("Monthly Revenue Split", className="kpi-label"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Subscription (fixed)", className="text-muted"),
                            html.Strong(format_mxn(split["subscription"])),
                        ],
                        className="revenue-split-row",
                    ),
                    html.Div(
                        [
                            html.Span("Usage (variable)", className="text-muted"),
                            html.Strong(format_mxn(split["usage"])),
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
        html.Div(format_mxn(split["total"]), className="kpi-value"),
        html.Div("Click for fixed / variable split", className="kpi-subtitle"),
    ]


def _display_rows(rows: list[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if key != "revenue_value"} for row in rows]


def _average_document_price(repo: SeedRepository, month: str) -> Decimal:
    active_plans = [repo.active_plan_for_client_month(client.id, month) for client in repo.active_clients(month)]
    document_prices = [Decimal(str(plan.price_per_document)) for plan in active_plans if plan.price_per_document > 0]
    if not document_prices:
        document_prices = [
            Decimal(str(plan.price_per_document)) for plan in repo.pricing_plans() if plan.price_per_document > 0
        ]
    if not document_prices:
        return Decimal("0")
    return sum(document_prices, Decimal("0")) / Decimal(len(document_prices))


def _margin_by_service(revenue: dict[str, Decimal], costs: dict[str, Decimal]) -> dict[str, Decimal]:
    return {service: amount - costs.get(service, Decimal("0")) for service, amount in revenue.items()}
