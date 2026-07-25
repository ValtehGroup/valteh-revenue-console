import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, dcc, html

from app.components.charts import bar_chart, line_chart
from app.components.tables import data_table
from app.data.repositories import SeedRepository
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
                dbc.Alert("There are no active clients for the latest available month.", color="secondary"),
            ]
        )
    default_client_id = _default_client_id(repo, clients)
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
                                options=[{"label": client.name, "value": client.id} for client in clients],
                                value=default_client_id,
                                clearable=False,
                            ),
                        ],
                        md=4,
                    )
                ],
                className="mb-4",
            ),
            html.Div(id="client-detail-content", children=_client_detail_content(default_client_id)),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("client-detail-content", "children"),
        Input("client-detail-client-filter", "value"),
    )
    def update_client_detail(client_id: int):
        return _client_detail_content(client_id)


def _client_detail_content(client_id: int):
    repo = SeedRepository()
    client = next(client for client in repo.clients() if client.id == client_id)
    months = repo.available_months()
    detail_month = _latest_client_month(repo, client.id, months)
    usage = repo.usage_for_client_month(client.id, detail_month)
    service_usage = {}
    service_cost = {}
    service_revenue = {}
    rates = repo.cost_rates(pd.Timestamp(f"{detail_month}-01").date())
    subscription = repo.active_subscription_for_client_month(client.id, detail_month)
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
                sum(float(event.quantity) for event in repo.usage_for_client_month(client.id, month))
                for month in months
            ],
            "operating_margin": [_client_operating_margin(repo, client.id, month) for month in months],
        }
    )
    usage_rows = [
        {
            "event_type": event.event_type,
            "quantity": float(event.quantity),
            "unit": event.unit,
            "timestamp": event.event_timestamp.strftime("%Y-%m-%d"),
            "source": event.source_system,
        }
        for event in usage
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
            html.H2(client.name, className="h5"),
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
            html.H2("Usage Events", className="h5"),
            data_table("client-usage-events", usage_rows, 10),
            html.H2("Invoices / Revenue Events", className="h5 mt-4"),
            data_table("client-revenue-events", invoice_rows, 10),
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
        if repo.active_subscription_for_client_month(client_id, month) is not None:
            return month
        if repo.usage_for_client_month(client_id, month):
            return month
    return months[-1]


def _client_operating_margin(repo: SeedRepository, client_id: int, month: str) -> float:
    profitability = repo.client_profitability(client_id, month)
    active_clients = repo.active_clients(month)
    active_client_ids = {client.id for client in active_clients}
    allocated_fixed_cost = (
        repo.monthly_summary(month)["fixed_cost"] / len(active_clients) if client_id in active_client_ids else 0
    )
    return float(
        calculate_operating_margin(
            profitability.revenue,
            profitability.variable_cost,
            allocated_fixed_cost,
        )
    )


def _revenue_type_label(revenue_type: str) -> str:
    labels = {
        "subscription": "Subscription (fixed)",
        "usage": "Usage (variable)",
    }
    return labels.get(revenue_type, revenue_type)
