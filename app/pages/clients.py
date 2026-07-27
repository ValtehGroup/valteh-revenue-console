from decimal import Decimal

import dash_bootstrap_components as dbc
from dash import Input, Output, html, no_update

from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.unit_economics import money
from app.pages.client_detail import detail_section
from app.utils.currency import format_mxn, format_percent


def layout():
    repo = SeedRepository()
    month = repo.available_months()[-1]
    rows = _client_rows(repo, month)
    return html.Div(
        [
            html.H1("Clients", className="h3"),
            html.P("Client status, economics, usage, and margin alerts.", className="text-muted"),
            dbc.Card(
                dbc.CardBody(data_table("clients-table", rows, 10)),
                className="content-card mb-4",
            ),
            detail_section(repo, repo.clients()),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("client-detail-client-filter", "value"),
        Input("clients-table", "active_cell"),
        prevent_initial_call=True,
    )
    def select_client_from_table(active_cell: dict | None):
        return _client_id_from_active_cell(active_cell)


def _client_id_from_active_cell(active_cell: dict | None):
    if not active_cell or active_cell.get("row_id") is None:
        return no_update
    return active_cell["row_id"]


def _client_rows(repo: SeedRepository, month: str) -> list[dict]:
    rows = []
    active_clients = repo.active_clients(month)
    active_client_ids = {client.id for client in active_clients}
    fixed_cost = repo.monthly_summary(month)["fixed_cost"]
    allocated_fixed_cost = fixed_cost / Decimal(len(active_clients)) if active_clients else Decimal("0")
    for client in repo.clients():
        is_active = client.id in active_client_ids
        usage = repo.usage_for_client_month(client.id, month)
        profitability = repo.client_profitability(client.id, month)
        plan = repo.active_plan_for_client_month(client.id, month) if is_active else None
        client_fixed_cost = allocated_fixed_cost if is_active else Decimal("0")
        operating_margin = profitability.gross_margin - client_fixed_cost
        margin_pct = operating_margin / money(profitability.revenue) if profitability.revenue else Decimal("0")
        alert = (
            "Inactive"
            if not is_active
            else (
                "Low margin"
                if margin_pct < Decimal("0.45")
                else "High usage" if sum(event.quantity for event in usage) > 6000 else "OK"
            )
        )
        rows.append(
            {
                "id": client.id,
                "client_name": client.name,
                "status": client.status,
                "active_services": ", ".join(sorted({event.service_code for event in usage})),
                "pricing_plan": plan.name if plan else "",
                "monthly_revenue": format_mxn(profitability.revenue),
                "monthly_usage": f"{sum(event.quantity for event in usage):,.0f}",
                "monthly_variable_cost": format_mxn(profitability.variable_cost),
                "allocated_fixed_cost": format_mxn(client_fixed_cost),
                "operating_margin": format_mxn(operating_margin),
                "operating_margin_percentage": format_percent(margin_pct),
                "alerts": alert,
            }
        )
    return rows
