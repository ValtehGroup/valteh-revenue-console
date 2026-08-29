import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from app.components.tables import data_table, status_cell_styles, table_data_styles
from app.data.client_repository import (
    ClientCommand,
    ClientManagementError,
    ClientRepository,
    ClientUpdateCommand,
)
from app.data.repositories import SeedRepository
from app.domain.display_currency import normalize_display_currency
from app.domain.unit_economics import money
from app.pages.client_detail import detail_section
from app.utils.currency import format_mxn, format_percent


def layout(display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    repo = SeedRepository()
    month = repo.available_months()[-1]
    clients = repo.clients()
    return html.Div(
        [
            dcc.Store(id="clients-refresh", data=0),
            dcc.Store(id="clients-action"),
            dcc.Store(id="clients-selected-row-id"),
            dcc.Store(id="clients-expected-updated-at"),
            html.H1("Clients", className="h3"),
            html.P("Client administration, economics, usage, and margin alerts.", className="text-muted"),
            html.Div(
                [
                    dbc.Button("Add client", id="client-add", color="primary"),
                    dbc.Button("Edit client", id="client-edit", outline=True, disabled=True),
                    dbc.Button("Change pricing plan", id="client-change-plan", outline=True, disabled=True),
                    dbc.Button(
                        "(De)activate client",
                        id="client-deactivate",
                        color="danger",
                        outline=True,
                        disabled=True,
                    ),
                    dbc.Button("Add reference", id="client-add-reference", outline=True, disabled=True),
                    dbc.Button("Deactivate reference", id="client-deactivate-reference", outline=True, disabled=True),
                    html.Div(
                        [
                            dbc.Label("Client status", html_for="client-status-filter", className="visually-hidden"),
                            dcc.Dropdown(
                                id="client-status-filter",
                                options=[
                                    {"label": "all", "value": "all"},
                                    {"label": "active", "value": "active"},
                                    {"label": "inactive", "value": "inactive"},
                                ],
                                value="all",
                                clearable=False,
                                persistence=True,
                                persistence_type="session",
                            ),
                        ],
                        style={"minWidth": "10rem"},
                    ),
                ],
                className="d-flex flex-wrap gap-2 align-items-center mb-3",
            ),
            dbc.Alert(id="client-management-message", is_open=False, dismissable=True),
            dbc.Card(
                dbc.CardBody(
                    data_table(
                        "clients-table",
                        _client_rows(repo, month),
                        10,
                        excluded_columns=["id", "status", "pricing_plan_id", "updated_at_raw"],
                    )
                ),
                className="content-card mb-4",
            ),
            detail_section(repo, clients, currency),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="client-action-title"), close_button=False),
                    dbc.ModalBody(
                        [
                            dbc.Alert(id="client-action-error", color="danger", is_open=False),
                            html.Div(id="client-action-body"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button("Cancel", id="client-action-cancel", outline=True),
                            dbc.Button("Save", id="client-action-submit", color="primary"),
                        ]
                    ),
                ],
                id="client-action-modal",
                is_open=False,
                scrollable=True,
                size="lg",
                backdrop="static",
                keyboard=True,
            ),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("clients-table", "data"),
        Output("clients-table", "active_cell"),
        Input("client-status-filter", "value"),
        Input("clients-refresh", "data"),
    )
    def refresh_clients_table(status: str, _refresh: int):
        repo = SeedRepository()
        return _client_rows(repo, repo.available_months()[-1], status), None

    @app.callback(
        Output("clients-selected-row-id", "data"),
        Output("clients-table", "style_data_conditional"),
        Output("client-detail-client-filter", "value"),
        Input("clients-table", "active_cell"),
        Input("client-status-filter", "value"),
        Input("clients-refresh", "data"),
    )
    def select_client_from_table(active_cell: dict | None, _status: str, _refresh: int):
        if ctx.triggered_id != "clients-table":
            return None, _client_table_styles(None), no_update
        client_id = _client_id_from_active_cell(active_cell)
        if client_id is no_update:
            return None, _client_table_styles(None), no_update
        return client_id, _client_table_styles(client_id), client_id

    @app.callback(
        Output("client-detail-client-filter", "options"),
        Input("clients-refresh", "data"),
    )
    def refresh_client_selector(_refresh: int):
        return _client_options(SeedRepository().clients())

    @app.callback(
        Output("client-edit", "disabled"),
        Output("client-change-plan", "disabled"),
        Output("client-deactivate", "disabled"),
        Output("client-add-reference", "disabled"),
        Output("client-deactivate-reference", "disabled"),
        Input("clients-selected-row-id", "data"),
        State("clients-table", "data"),
    )
    def enable_client_actions(selected_id: int | None, rows: list[dict] | None):
        selected = _selected_client(selected_id, rows)
        disabled = selected is None
        has_references = bool(selected and ClientRepository().list_references(selected_id, include_inactive=False))
        change_plan_disabled = disabled or selected.get("client_status") != "active"
        return disabled, change_plan_disabled, disabled, disabled, disabled or not has_references

    @app.callback(
        Output("client-action-modal", "is_open"),
        Output("client-action-title", "children"),
        Output("client-action-body", "children"),
        Output("clients-action", "data"),
        Output("clients-expected-updated-at", "data"),
        Output("client-action-error", "children"),
        Output("client-action-error", "is_open"),
        Output("client-management-message", "children"),
        Output("client-management-message", "color"),
        Output("client-management-message", "is_open"),
        Output("clients-refresh", "data"),
        Input("client-add", "n_clicks"),
        Input("client-edit", "n_clicks"),
        Input("client-change-plan", "n_clicks"),
        Input("client-deactivate", "n_clicks"),
        Input("client-add-reference", "n_clicks"),
        Input("client-deactivate-reference", "n_clicks"),
        Input("client-action-cancel", "n_clicks"),
        Input("client-action-submit", "n_clicks"),
        State("clients-selected-row-id", "data"),
        State("clients-table", "data"),
        State("clients-action", "data"),
        State("clients-expected-updated-at", "data"),
        State({"type": "client-field", "name": ALL}, "id"),
        State({"type": "client-field", "name": ALL}, "value"),
        State("clients-refresh", "data"),
        prevent_initial_call=True,
        running=[(Output("client-action-submit", "disabled"), True, False)],
    )
    def manage_client(
        _add,
        _edit,
        _change_plan,
        _deactivate,
        _add_reference,
        _deactivate_reference,
        _cancel,
        _submit,
        selected_id,
        table_rows,
        action,
        expected_updated_at,
        field_ids,
        field_values,
        refresh,
    ):
        defaults = (no_update,) * 11
        trigger = ctx.triggered_id
        if trigger == "client-action-cancel":
            return False, no_update, no_update, None, None, no_update, False, no_update, no_update, False, no_update
        if trigger != "client-action-submit":
            action = {
                "client-add": "add",
                "client-edit": "edit",
                "client-change-plan": "change_plan",
                "client-add-reference": "add_reference",
                "client-deactivate-reference": "deactivate_reference",
            }.get(trigger)
            selected = _selected_client(selected_id, table_rows) if action != "add" else None
            if trigger == "client-deactivate" and selected is not None:
                action = "reactivate" if selected.get("client_status") == "inactive" else "deactivate"
            if action != "add" and selected is None:
                return (
                    False,
                    no_update,
                    no_update,
                    None,
                    None,
                    no_update,
                    False,
                    "Select one client first.",
                    "warning",
                    True,
                    no_update,
                )
            return (
                True,
                _action_title(action),
                _action_form(action, selected),
                action,
                selected.get("updated_at_raw") if selected else None,
                no_update,
                False,
                no_update,
                no_update,
                False,
                no_update,
            )
        if not action:
            return defaults
        selected = _selected_client(selected_id, table_rows) if action != "add" else None
        values = {item["name"]: value for item, value in zip(field_ids, field_values, strict=True)}
        try:
            _execute_client_action(action, selected, values, expected_updated_at)
        except ClientManagementError as exc:
            return (
                True,
                no_update,
                no_update,
                action,
                expected_updated_at,
                str(exc),
                True,
                no_update,
                no_update,
                False,
                no_update,
            )
        return (
            False,
            no_update,
            no_update,
            None,
            None,
            no_update,
            False,
            _success_message(action),
            "success",
            True,
            (refresh or 0) + 1,
        )


def _client_id_from_active_cell(active_cell: dict | None):
    if not active_cell or active_cell.get("row_id") is None:
        return no_update
    return active_cell["row_id"]


def _client_rows(repo: SeedRepository, month: str, status: str = "all") -> list[dict]:
    rows = []
    clients = repo.clients()
    if status != "all":
        clients = [client for client in clients if client.status == status]
    economic_clients = repo.active_clients(month)
    economic_client_ids = {client.id for client in economic_clients}
    fixed_cost = repo.monthly_summary(month)["fixed_cost"]
    allocated_fixed_cost = fixed_cost / Decimal(len(economic_clients)) if economic_clients else Decimal("0")
    for client in clients:
        economically_active = client.id in economic_client_ids
        usage = repo.usage_for_client_month(client.id, month)
        profitability = repo.client_profitability(client.id, month)
        plan = repo.active_plan_for_client_month(client.id, month) if economically_active else None
        client_fixed_cost = allocated_fixed_cost if economically_active else Decimal("0")
        operating_margin = profitability.gross_margin - client_fixed_cost
        margin_pct = operating_margin / money(profitability.revenue) if profitability.revenue else Decimal("0")
        rows.append(
            {
                "id": client.id,
                "client_id": client.client_code,
                "client_name": client.name,
                "client_type": client.client_type,
                "status": client.status,
                "client_status": client.status,
                "start_date": client.start_date.isoformat(),
                "end_date": client.end_date.isoformat() if client.end_date else "",
                "pricing_plan": plan.name if plan else "No active plan",
                "pricing_plan_id": plan.id if plan else None,
                "monthly_revenue": format_mxn(profitability.revenue),
                "monthly_usage": f"{sum(event.quantity for event in usage):,.0f}",
                "monthly_variable_cost": format_mxn(profitability.variable_cost),
                "allocated_fixed_cost": format_mxn(client_fixed_cost),
                "operating_margin": format_mxn(operating_margin),
                "operating_margin_percentage": format_percent(margin_pct),
                "alerts": _client_alert(client.status, plan, usage, margin_pct),
                "created_at": _format_utc(client.created_at),
                "updated_at": _format_utc(client.updated_at),
                "notes": client.notes or "",
                "updated_at_raw": client.updated_at.isoformat() if client.updated_at else "",
            }
        )
    return rows


def _client_alert(status: str, plan, usage: list, margin_pct: Decimal) -> str:
    if status == "inactive":
        return "Inactive"
    if plan is None:
        return "No active plan"
    if not usage:
        return "No usage recorded"
    if margin_pct < Decimal("0.45"):
        return "Low margin"
    if sum(event.quantity for event in usage) > 6000:
        return "High usage"
    return "OK"


def _selected_client(selected_id: int | None, rows: list[dict] | None) -> dict | None:
    if selected_id is None or not rows:
        return None
    return next((row for row in rows if row.get("id") == selected_id), None)


def _client_table_styles(selected_id: int | None) -> list[dict]:
    styles = table_data_styles()
    if selected_id is not None:
        styles.append(
            {
                "if": {"filter_query": f"{{id}} = {selected_id}"},
                "backgroundColor": "var(--color-surface-soft)",
                "borderTop": "2px solid var(--color-primary)",
                "borderBottom": "2px solid var(--color-primary)",
                "color": "var(--color-text)",
                "fontWeight": "600",
            }
        )
    styles.extend(status_cell_styles("client_status"))
    return styles


def _client_options(clients) -> list[dict]:
    return [{"label": f"{client.client_code} — {client.name}", "value": client.id} for client in clients]


def _field(name: str, label: str, value=None, *, kind: str = "text", required: bool = False, options=None):
    field_id = {"type": "client-field", "name": name}
    html_id = json.dumps(field_id, separators=(",", ":"))
    if options is not None:
        control = dcc.Dropdown(id=field_id, options=options, value=value, clearable=False)
    elif kind == "textarea":
        control = dbc.Textarea(id=field_id, value=value or "", rows=3)
    else:
        control = dbc.Input(id=field_id, value=value, type=kind, required=required)
    return html.Div([dbc.Label(label, html_for=html_id), control], className="mb-3")


def _action_title(action: str) -> str:
    return {
        "add": "Add client",
        "edit": "Edit client",
        "change_plan": "Change pricing plan",
        "deactivate": "Deactivate client",
        "reactivate": "Reactivate client",
        "add_reference": "Add external reference",
        "deactivate_reference": "Deactivate external reference",
    }[action]


def _action_form(action: str, selected: dict | None):
    selected = selected or {}
    if action == "change_plan":
        pricing_plans = SeedRepository().pricing_plans(client_id=int(selected["id"]))
        current_plan_id = selected.get("pricing_plan_id")
        default_plan = next((plan for plan in pricing_plans if plan.id != current_plan_id), None)
        return html.Div(
            [
                html.P([html.Strong(selected.get("client_name", "")), html.Br(), selected.get("client_id", "")]),
                dbc.Alert(
                    "The current subscription will end the day before the effective date. "
                    "The client ID and all prior subscription, usage, revenue, and margin history are retained.",
                    color="info",
                ),
                _field(
                    "pricing_plan_id",
                    "New pricing plan",
                    default_plan.id if default_plan else None,
                    required=True,
                    options=[{"label": plan.name, "value": plan.id} for plan in pricing_plans],
                ),
                _field(
                    "effective_from",
                    "Effective from",
                    _next_month_start().isoformat(),
                    kind="date",
                    required=True,
                ),
            ]
        )
    if action == "deactivate":
        return html.Div(
            [
                html.P([html.Strong(selected.get("client_name", "")), html.Br(), selected.get("client_id", "")]),
                dbc.Alert("The client and all historical usage and revenue will be retained.", color="warning"),
                _field("end_date", "Effective deactivation date", kind="date", required=True),
            ]
        )
    if action == "reactivate":
        return html.Div(
            [
                html.P([html.Strong(selected.get("client_name", "")), html.Br(), selected.get("client_id", "")]),
                dbc.Alert(
                    "Reactivation changes the client status to Active and clears the End Date. "
                    "Historical usage remains unchanged, and no pricing plan is recreated automatically.",
                    color="info",
                ),
            ]
        )
    if action == "add_reference":
        return html.Div(
            [
                html.P(f"Client ID: {selected.get('client_id', '')}"),
                _reference_example(),
                _field("source_system", "Source system", required=True),
                _field("external_client_reference", "External client reference", required=True),
            ]
        )
    if action == "deactivate_reference":
        references = ClientRepository().list_references(selected["id"], include_inactive=False)
        return html.Div(
            [
                dbc.Alert("The mapping will remain stored for audit and historical traceability.", color="warning"),
                _field(
                    "reference_id",
                    "External reference",
                    references[0].id if references else None,
                    options=[
                        {
                            "label": f"{reference.source_system}: {reference.external_client_reference}",
                            "value": reference.id,
                        }
                        for reference in references
                    ],
                ),
            ]
        )
    fields = []
    if action == "edit":
        fields.append(
            dbc.Alert(f"Client ID {selected.get('client_id')} is permanent and cannot be edited.", color="info")
        )
    fields.extend(
        [
            _field("name", "Name", selected.get("client_name"), required=True),
            _field("client_type", "Client type", selected.get("client_type"), required=True),
            _field(
                "start_date",
                "Start date",
                selected.get("start_date") or date.today().isoformat(),
                kind="date",
                required=True,
            ),
            _field("notes", "Notes", selected.get("notes"), kind="textarea"),
        ]
    )
    if action == "add":
        pricing_plans = SeedRepository().pricing_plans(reusable_only=True)
        fields.extend(
            [
                html.H3("Initial pricing", className="h6"),
                _field(
                    "pricing_plan_id",
                    "Pricing plan",
                    pricing_plans[0].id if pricing_plans else None,
                    required=True,
                    options=[{"label": plan.name, "value": plan.id} for plan in pricing_plans],
                ),
                html.H3("Optional initial external reference", className="h6"),
                _reference_example(),
                _field("source_system", "Source system"),
                _field("external_client_reference", "External client reference"),
            ]
        )
    return html.Div(fields)


def _execute_client_action(action: str, selected: dict | None, values: dict, expected_updated_at: str | None) -> None:
    repository = ClientRepository()
    if action == "add":
        if not values.get("pricing_plan_id"):
            raise ClientManagementError("Select an initial pricing plan.")
        repository.create_client(
            ClientCommand(
                name=values.get("name"),
                client_type=values.get("client_type"),
                start_date=values.get("start_date"),
                notes=values.get("notes"),
                source_system=values.get("source_system"),
                external_client_reference=values.get("external_client_reference"),
                pricing_plan_id=values.get("pricing_plan_id"),
            )
        )
        return
    if selected is None:
        raise ClientManagementError("The selected client is no longer available. Refresh and try again.")
    client_id = int(selected["id"])
    if action == "edit":
        if not expected_updated_at:
            raise ClientManagementError("The selected client is stale. Refresh and try again.")
        repository.update_client(
            client_id,
            ClientUpdateCommand(
                name=values.get("name"),
                client_type=values.get("client_type"),
                start_date=values.get("start_date"),
                notes=values.get("notes"),
            ),
            expected_updated_at,
        )
    elif action == "change_plan":
        if not expected_updated_at:
            raise ClientManagementError("The selected client is stale. Refresh and try again.")
        repository.change_pricing_plan(
            client_id,
            values.get("pricing_plan_id"),
            values.get("effective_from"),
            expected_updated_at,
        )
    elif action == "deactivate":
        if not expected_updated_at:
            raise ClientManagementError("The selected client is stale. Refresh and try again.")
        repository.deactivate_client(client_id, values.get("end_date"), expected_updated_at)
    elif action == "reactivate":
        if not expected_updated_at:
            raise ClientManagementError("The selected client is stale. Refresh and try again.")
        repository.reactivate_client(client_id, expected_updated_at)
    elif action == "add_reference":
        repository.add_reference(client_id, values.get("source_system"), values.get("external_client_reference"))
    elif action == "deactivate_reference":
        repository.deactivate_reference(int(values.get("reference_id")))


def _success_message(action: str) -> str:
    return {
        "add": "Client created successfully.",
        "edit": "Client updated successfully.",
        "change_plan": "Pricing plan changed; the previous subscription history was retained.",
        "deactivate": "Client deactivated; historical data was retained.",
        "reactivate": "Client reactivated. Add a pricing plan separately if needed.",
        "add_reference": "External reference added successfully.",
        "deactivate_reference": "External reference deactivated successfully.",
    }[action]


def _reference_example() -> dbc.Alert:
    return dbc.Alert(
        [
            "Example: if SAREMI sends ",
            html.Code('"client_reference": "notaria-38-qro"'),
            ", enter ",
            html.Strong("saremi"),
            " as Source system and ",
            html.Strong("notaria-38-qro"),
            " as External client reference. This is a tenant/customer identifier, not an API key.",
        ],
        color="info",
    )


def _format_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _next_month_start(today: date | None = None) -> date:
    today = today or date.today()
    return (today.replace(day=28) + timedelta(days=4)).replace(day=1)
