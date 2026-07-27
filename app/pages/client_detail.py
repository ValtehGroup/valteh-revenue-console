import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, dcc, html

from app.components.charts import bar_chart, line_chart
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.cost_engine import calculate_variable_cost
from app.domain.revenue_engine import calculate_client_revenue
from app.domain.unit_economics import calculate_operating_margin
from app.utils.currency import format_mxn


def layout():
    repo = SeedRepository()
    clients = repo.clients()
    return html.Div(
        [
            html.H1("Clients", className="h3"),
            html.P("Client-specific usage, revenue, cost, and margin history.", className="text-muted"),
            detail_section(repo, clients),
        ]
    )


def detail_section(repo: SeedRepository, clients) -> html.Div:
    if not clients:
        return html.Div(
            [
                dbc.Alert("There are no clients yet.", color="secondary"),
            ]
        )
    default_client_id = _default_client_id(repo, clients)
    months = repo.available_months()
    default_month = _latest_client_month(repo, default_client_id, months)
    return html.Div(
        [
            html.H2("Client Detail", className="h4"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Client"),
                            dcc.Dropdown(
                                id="client-detail-client-filter",
                                options=[
                                    {"label": f"{client.client_code} — {client.name}", "value": client.id}
                                    for client in clients
                                ],
                                value=default_client_id,
                                clearable=False,
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        md=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Period"),
                            dcc.Dropdown(
                                id="client-detail-month-filter",
                                options=_month_options(months),
                                value=default_month,
                                clearable=False,
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        md=3,
                    ),
                ],
                className="mb-4",
            ),
            html.Div(id="client-detail-content", children=_client_detail_content(default_client_id, default_month)),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("client-detail-month-filter", "value"),
        Input("client-detail-client-filter", "value"),
        prevent_initial_call=True,
    )
    def select_latest_client_period(client_id: int | None):
        repo = SeedRepository()
        if client_id is None:
            return repo.available_months()[-1]
        return _latest_client_month(repo, client_id, repo.available_months())

    @app.callback(
        Output("client-detail-content", "children"),
        Input("client-detail-client-filter", "value"),
        Input("client-detail-month-filter", "value"),
        Input("clients-refresh", "data"),
    )
    def update_client_detail(client_id: int, month: str, _refresh: int):
        return _client_detail_content(client_id, month)


def _client_detail_content(client_id: int | None, selected_month: str | None = None):
    repo = SeedRepository()
    client = next((client for client in repo.clients() if client.id == client_id), None)
    if client is None:
        return dbc.Alert("The selected client is no longer available.", color="warning")
    months = repo.available_months()
    detail_month = selected_month if selected_month in months else _latest_client_month(repo, client.id, months)
    usage = repo.usage_history_for_client_month(client.id, detail_month)
    service_usage = {}
    service_cost = {}
    service_revenue = {}
    rates = repo.cost_rates(pd.Timestamp(f"{detail_month}-01").date())
    subscription = repo.subscription_for_client_month(client.id, detail_month)
    plan = (
        next(plan for plan in repo.pricing_plans() if plan.id == subscription.pricing_plan_id) if subscription else None
    )
    for event in usage:
        service_usage[event.service_code] = service_usage.get(event.service_code, 0) + float(event.quantity)
        service_cost[event.service_code] = service_cost.get(event.service_code, 0) + float(event.quantity) * float(
            rates.get(event.event_type, 0)
        )
        service_revenue[event.service_code] = service_revenue.get(event.service_code, 0) + (
            _event_price(event.event_type, plan) * float(event.quantity) if plan else 0
        )
    trend = pd.DataFrame(
        {
            "month": months,
            "usage": [
                sum(float(event.quantity) for event in repo.usage_history_for_client_month(client.id, month))
                for month in months
            ],
            "operating_margin": [_client_operating_margin(repo, client.id, month) for month in months],
        }
    )
    historical_usage = sorted(
        (event for event in repo.usage_events() if event.client_id == client.id),
        key=lambda event: event.event_timestamp,
        reverse=True,
    )
    usage_rows = [
        {
            "event_type": event.event_type,
            "quantity": float(event.quantity),
            "unit": event.unit,
            "timestamp": event.event_timestamp.strftime("%Y-%m-%d"),
            "source": event.source_system,
        }
        for event in historical_usage
    ]
    invoice_rows = [
        {
            "date": event.event_timestamp.strftime("%Y-%m-%d"),
            "income_type": _revenue_type_label(event.revenue_type),
            "amount": format_mxn(event.amount),
            "description": event.description,
        }
        for event in sorted(repo.revenue_events(), key=lambda item: (item.event_timestamp, item.revenue_type))
        if event.client_id == client.id
    ]
    return html.Div(
        [
            html.H2(f"{client.name} · {client.client_code}", className="h5"),
            dbc.Alert("No pricing plan for the selected period", color="secondary", is_open=plan is None),
            dbc.Alert("No usage recorded for the selected period", color="secondary", is_open=not usage),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=bar_chart(service_usage, "Usage by Service")), md=4),
                    dbc.Col(dcc.Graph(figure=bar_chart(service_revenue, "Revenue by Service")), md=4),
                    dbc.Col(dcc.Graph(figure=bar_chart(service_cost, "Cost by Service")), md=4),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=line_chart(trend, "month", "usage", "Historical Usage Trend")), md=6),
                    dbc.Col(
                        dcc.Graph(figure=line_chart(trend, "month", "operating_margin", "Historical Margin Trend")),
                        md=6,
                    ),
                ],
                className="mb-4",
            ),
            html.Details(
                [
                    html.Summary("Usage Events", className="h5"),
                    html.Div(data_table("client-usage-events", usage_rows, 10), className="mt-3"),
                ],
                className="mb-3",
            ),
            html.Details(
                [
                    html.Summary("Invoices / Revenue Events", className="h5"),
                    html.Div(data_table("client-revenue-events", invoice_rows, 10), className="mt-3"),
                ],
                className="mb-3",
            ),
        ]
    )


def _event_price(event_type: str, plan) -> float:
    price_map = {
        "saremi.document_validation": plan.price_per_document,
        "saremi.ine_validation": plan.price_per_validation,
        "graphos.query": plan.price_per_graph_query,
        "graphos.case_analysis": plan.price_per_graph_query,
        "blockchain.asiento_registration": plan.price_per_blockchain_transaction,
        "blockchain.folio_mint": plan.price_per_property_mint,
    }
    return float(price_map.get(event_type, 0))


def _default_client_id(repo: SeedRepository, clients) -> int:
    latest_month = repo.available_months()[-1]
    active_clients = repo.active_clients(latest_month)
    if active_clients:
        return active_clients[0].id
    return clients[0].id


def _latest_client_month(repo: SeedRepository, client_id: int, months: list[str]) -> str:
    for month in reversed(months):
        if repo.usage_history_for_client_month(client_id, month):
            return month
    for month in reversed(months):
        if repo.subscription_for_client_month(client_id, month) is not None:
            return month
    return months[-1]


def _client_operating_margin(repo: SeedRepository, client_id: int, month: str) -> float:
    usage = repo.usage_history_for_client_month(client_id, month)
    subscription = repo.subscription_for_client_month(client_id, month)
    plan = next(
        (plan for plan in repo.pricing_plans() if subscription and plan.id == subscription.pricing_plan_id),
        None,
    )
    revenue = (
        calculate_client_revenue(usage, plan, subscription, pd.Timestamp(f"{month}-01").date()) if plan else 0
    )
    variable_cost = calculate_variable_cost(usage, repo.cost_items())
    historical_client_ids = {
        client.id
        for client in repo.clients()
        if repo.subscription_for_client_month(client.id, month) is not None
    }
    allocated_fixed_cost = (
        repo.monthly_summary(month)["fixed_cost"] / len(historical_client_ids)
        if client_id in historical_client_ids
        else 0
    )
    return float(
        calculate_operating_margin(
            revenue,
            variable_cost,
            allocated_fixed_cost,
        )
    )


def _month_options(months: list[str]) -> list[dict[str, str]]:
    return [
        {"label": pd.Timestamp(f"{month}-01").strftime("%B %Y"), "value": month}
        for month in reversed(months)
    ]


def _revenue_type_label(revenue_type: str) -> str:
    labels = {
        "subscription": "Subscription (fixed)",
        "usage": "Usage (variable)",
    }
    return labels.get(revenue_type, revenue_type)
