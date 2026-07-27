from dash import html

from app.components.tables import data_table
from app.data.client_repository import ClientRepository
from app.data.repositories import SeedRepository


def layout():
    repo = SeedRepository()
    rows = _usage_rows(repo)
    return html.Div(
        [
            html.H1("Usage", className="h3"),
            html.P("Seeded operational usage events by service line.", className="text-muted"),
            data_table("usage-table", rows, 15, excluded_columns=["client_id"]),
        ]
    )


def _usage_rows(repo: SeedRepository, reference_repository: ClientRepository | None = None) -> list[dict]:
    clients = {client.id: client for client in repo.clients()}
    reference_repository = reference_repository or ClientRepository()
    references_by_client_source = {
        (reference.client_id, reference.source_system): reference.external_client_reference
        for client_id in clients
        for reference in reference_repository.list_references(client_id, include_inactive=False)
    }
    rows = [
        {
            "client_id": event.client_id,
            "client_code": clients[event.client_id].client_code if event.client_id in clients else "Unresolved",
            "client_name": clients[event.client_id].name if event.client_id in clients else "Unknown client",
            "service_code": event.service_code,
            "event_type": event.event_type,
            "quantity": float(event.quantity),
            "unit": event.unit,
            "timestamp": event.event_timestamp.strftime("%Y-%m-%d"),
            "source_system": event.source_system,
            "external_client_reference": references_by_client_source.get(
                (event.client_id, event.source_system.lower()), ""
            ),
            "resolution_status": "Resolved" if event.client_id in clients else "Unresolved",
        }
        for event in repo.usage_events()
    ]
    return rows
