from collections import defaultdict
from decimal import Decimal

from dash import html

from app.components.tables import data_grid


def anthropic_cost_breakdown(presentation: dict, clients, grid_id: str):
    names = {client.id: client.name for client in clients}
    labels = {
        "internal": "Internal development / testing",
        "production_unassigned": "Production pending client allocation",
        "client": "Assigned production",
        "unassigned": "Pending API-key allocation",
    }
    totals = defaultdict(lambda: Decimal("0"))
    for amount, value in presentation["translated_costs"]:
        if amount.cost_key == "anthropic.billed":
            totals[(amount.name, amount.cost_scope, amount.client_id)] += value
    rows = [
        {
            "api_key": name,
            "allocation": labels[scope],
            "client": names.get(client_id, "Unassigned") if scope != "internal" else "Valteh internal",
            "amount": float(value),
        }
        for (name, scope, client_id), value in sorted(totals.items(), key=lambda item: item[0][0])
    ]
    return html.Div(
        [
            html.H3("Anthropic realized variable costs", className="h5"),
            html.P(
                "Historical billed costs allocated by API-key usage. Development and sandbox belong to Valteh; "
                "production remains unassigned until you assign its API key in Usage. "
                "Synced Claude costs replace the catalog Claude rate for the same dates. "
                "Claude Tokens Prod/Dev catalog allowances are excluded from realized fixed costs. "
                "Local SAREMI processing and validation costs are separate. Unsynced days are not measured zero.",
                className="small text-muted",
            ),
            (
                data_grid(grid_id, rows, 10, currency=presentation["currency"])
                if rows
                else html.P("No historical billed costs loaded for this period.", className="text-muted")
            ),
        ],
        className="mb-4",
    )
