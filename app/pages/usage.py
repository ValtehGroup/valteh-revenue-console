from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

from app.components.chart_theme import apply_chart_theme
from app.components.kpi_card import kpi_card
from app.components.tables import data_table
from app.config import get_settings
from app.data.anthropic_assignment_repository import (
    ENVIRONMENT_SOURCES,
    AnthropicAssignmentError,
    AnthropicAssignmentRepository,
    AnthropicKeyAssignmentCommand,
)
from app.data.client_repository import ClientRepository
from app.data.repositories import SeedRepository
from app.domain.anthropic_cost_allocation import allocate_anthropic_costs
from app.integrations.anthropic_admin_api import (
    MAX_REPORT_DAYS,
    AnthropicAdminAPIError,
    AnthropicAdminClient,
    AnthropicAdminReport,
)

ALL_FILTER_VALUE = "__all__"
UNASSIGNED_VALUE = "unassigned"
GROUP_LABELS = {
    "api_key": "API key",
    "client": "Client",
    "environment": "Environment",
    "model": "Model",
}


def layout():
    repo = SeedRepository()
    rows = _usage_rows(repo)
    today = date.today()
    default_start = today - timedelta(days=6)
    anthropic_is_configured = get_settings().anthropic_admin_key is not None
    return html.Div(
        [
            html.H1("Usage", className="h3"),
            html.P("Operational usage events by service line.", className="text-muted"),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H2("Anthropic usage and cost allocation", className="h5"),
                        html.P(
                            "Loaded server-side from the Anthropic Admin API. The Admin API key is never sent "
                            "to the browser.",
                            className="text-muted",
                        ),
                        dbc.Alert(
                            (
                                "Admin API key configured. Choose a range and load the report."
                                if anthropic_is_configured
                                else "Admin API key not configured. Paste it into ANTHROPIC_ADMIN_KEY in .env "
                                "and restart the server."
                            ),
                            color="success" if anthropic_is_configured else "warning",
                            className="mb-3",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Label(
                                            "Report range",
                                            html_for="claude-report-range",
                                            className="small mb-1",
                                        ),
                                        dcc.DatePickerRange(
                                            id="claude-report-range",
                                            start_date=default_start,
                                            end_date=today,
                                            max_date_allowed=today,
                                            display_format="YYYY-MM-DD",
                                            minimum_nights=0,
                                            persistence=True,
                                            persistence_type="session",
                                        ),
                                    ]
                                ),
                                dbc.Button(
                                    "Load Claude report",
                                    id="claude-load-report",
                                    color="primary",
                                    disabled=not anthropic_is_configured,
                                ),
                            ],
                            className="d-flex flex-wrap gap-3 align-items-end mb-3",
                        ),
                        html.P(
                            f"A report can include up to {MAX_REPORT_DAYS} days. Data is requested only when "
                            "you press the button.",
                            className="small text-muted",
                        ),
                        dcc.Loading(html.Div(id="claude-report-content"), type="circle"),
                    ]
                ),
                className="content-card mb-4",
            ),
            html.H2("Operational usage", className="h5"),
            data_table("usage-table", rows, 15, excluded_columns=["client_id"]),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("claude-report-content", "children"),
        Input("claude-load-report", "n_clicks"),
        State("claude-report-range", "start_date"),
        State("claude-report-range", "end_date"),
        prevent_initial_call=True,
    )
    def load_claude_report(_clicks: int, starting_at: str | None, ending_at: str | None):
        return _claude_report_content(starting_at, ending_at)

    @app.callback(
        Output("anthropic-analysis-summary-content", "children"),
        Output("anthropic-over-time-chart", "figure"),
        Output("anthropic-analysis-details-content", "children"),
        Input("anthropic-report-data", "data"),
        Input("anthropic-workspace-filter", "value"),
        Input("anthropic-api-key-filter", "value"),
        Input("anthropic-model-filter", "value"),
        Input("anthropic-environment-filter", "value"),
        Input("anthropic-client-filter", "value"),
        Input("anthropic-group-by", "value"),
        Input("anthropic-chart-metric", "value"),
        Input("anthropic-assignment-version", "data"),
    )
    def update_analysis(
        report_data: dict[str, Any] | None,
        workspace_id: str | None,
        api_key_id: str | None,
        model: str | None,
        environment: str | None,
        client_id: str | int | None,
        group_by: str | None,
        chart_metric: str | None,
        _assignment_version: int | None,
    ):
        if not report_data:
            return dbc.Alert("Load a report to analyze usage.", color="secondary"), go.Figure(), html.Div()
        return _analysis_sections(
            report_data,
            workspace_id or ALL_FILTER_VALUE,
            api_key_id or ALL_FILTER_VALUE,
            model or ALL_FILTER_VALUE,
            environment or ALL_FILTER_VALUE,
            client_id or ALL_FILTER_VALUE,
            group_by if group_by in GROUP_LABELS else "api_key",
            chart_metric if chart_metric in {"usage", "cost"} else "usage",
        )

    @app.callback(
        Output("anthropic-assignment-message", "children"),
        Output("anthropic-assignment-message", "color"),
        Output("anthropic-assignment-message", "is_open"),
        Output("anthropic-assignment-version", "data"),
        Input("anthropic-save-assignments", "n_clicks"),
        State("anthropic-assignment-table", "data"),
        State("anthropic-assignment-version", "data"),
        prevent_initial_call=True,
    )
    def save_assignments(
        _clicks: int,
        rows: list[dict[str, Any]] | None,
        assignment_version: int | None,
    ):
        if rows is None:
            return "No API-key assignments were available to save.", "warning", True, no_update
        try:
            commands = _assignment_commands(rows)
            AnthropicAssignmentRepository().save_assignments(commands)
        except (AnthropicAssignmentError, TypeError, ValueError) as exc:
            return str(exc), "danger", True, no_update
        return (
            "Assignments saved. The cost analysis has been refreshed.",
            "success",
            True,
            int(assignment_version or 0) + 1,
        )


def _claude_report_content(
    starting_at: str | None,
    ending_at: str | None,
    client: AnthropicAdminClient | None = None,
):
    if not starting_at or not ending_at:
        return dbc.Alert("Select both a start date and an end date.", color="warning")

    settings = get_settings()
    secret = settings.anthropic_admin_key
    if client is None:
        if secret is None:
            return dbc.Alert(
                "Admin API key is not configured. Update .env and restart the server.",
                color="warning",
            )
        client = AnthropicAdminClient(secret.get_secret_value())

    try:
        start_date = date.fromisoformat(starting_at[:10])
        end_date = date.fromisoformat(ending_at[:10])
        report = client.fetch_report(start_date, end_date)
    except ValueError as exc:
        return dbc.Alert(str(exc), color="warning")
    except AnthropicAdminAPIError as exc:
        return dbc.Alert(str(exc), color="danger")

    return _render_claude_report(report, start_date, end_date)


def _render_claude_report(report: AnthropicAdminReport, starting_at: date, ending_at: date) -> html.Div:
    report_data = _serialize_report(report, starting_at, ending_at)
    clients = ClientRepository().list_clients()
    assignment_rows = _assignment_rows(report_data, clients)
    filter_options = _report_filter_options(report_data, clients)

    return html.Div(
        [
            dcc.Store(id="anthropic-report-data", data=report_data),
            dcc.Store(id="anthropic-assignment-version", data=0),
            html.P(
                f"Report loaded for {starting_at.isoformat()} through {ending_at.isoformat()} (UTC).",
                className="small text-muted",
            ),
            html.Div(
                [
                    _filter_control("Workspace", "anthropic-workspace-filter", filter_options["workspaces"]),
                    _filter_control("API key", "anthropic-api-key-filter", filter_options["api_keys"]),
                    _filter_control("Model", "anthropic-model-filter", filter_options["models"]),
                    _filter_control("Environment", "anthropic-environment-filter", filter_options["environments"]),
                    _filter_control("Client", "anthropic-client-filter", filter_options["clients"]),
                    _filter_control(
                        "Group by",
                        "anthropic-group-by",
                        [{"label": label, "value": value} for value, label in GROUP_LABELS.items()],
                        value="api_key",
                        include_all=False,
                    ),
                ],
                className="d-flex flex-wrap gap-3 align-items-end mb-4",
            ),
            dcc.Loading(
                html.Div(
                    [
                        html.Div(id="anthropic-analysis-summary-content"),
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    _chart_metric_control(),
                                    dcc.Graph(
                                        id="anthropic-over-time-chart",
                                        figure=go.Figure(),
                                        config={"displaylogo": False, "responsive": True},
                                    ),
                                ]
                            ),
                            className="content-card mb-4",
                        ),
                        html.Div(id="anthropic-analysis-details-content"),
                    ]
                ),
                type="circle",
            ),
            html.Hr(className="my-4"),
            html.H3("Assign API keys to clients", className="h5"),
            html.P(
                "Choose one environment and client for each API key. Saving stores the mapping in the "
                "dashboard database; it does not modify the key in Anthropic.",
                className="text-muted",
            ),
            (
                data_table(
                    "anthropic-assignment-table",
                    assignment_rows,
                    max(len(assignment_rows), 5),
                    editable=False,
                    column_options={
                        "environment": {"presentation": "dropdown", "editable": True},
                        "client_id": {"name": "Client", "presentation": "dropdown", "editable": True},
                    },
                    dropdown={
                        "environment": {
                            "options": [
                                {"label": environment.title(), "value": environment}
                                for environment in ENVIRONMENT_SOURCES
                            ]
                        },
                        "client_id": {
                            "options": [{"label": "Unassigned", "value": ""}]
                            + [
                                {"label": f"{client.name} ({client.client_code})", "value": client.id}
                                for client in clients
                            ]
                        },
                    },
                )
                if assignment_rows
                else dbc.Alert("Anthropic returned no API keys to assign.", color="secondary")
            ),
            dbc.Button(
                "Save assignments",
                id="anthropic-save-assignments",
                color="primary",
                className="mt-3",
                disabled=not assignment_rows,
            ),
            dbc.Alert(id="anthropic-assignment-message", is_open=False, className="mt-3"),
            html.Details(
                [
                    html.Summary("Raw Anthropic report details", className="fw-semibold"),
                    _raw_report_details(report_data),
                ],
                className="mt-4",
            ),
        ]
    )


def _serialize_report(report: AnthropicAdminReport, starting_at: date, ending_at: date) -> dict[str, Any]:
    allocation = allocate_anthropic_costs(report.messages_usage_rows, report.cost_rows)
    return {
        "starting_at": starting_at.isoformat(),
        "ending_at": ending_at.isoformat(),
        "billed_cost_usd": str(report.billed_organization_cost_usd),
        "allocated_cost_usd": str(allocation.allocated_cost_usd),
        "unallocated_cost_usd": str(allocation.unallocated_cost_usd),
        "api_keys": [
            {
                "id": key.id,
                "name": key.name,
                "status": key.status,
                "workspace_id": key.workspace_id,
                "partial_key_hint": key.partial_key_hint,
            }
            for key in report.api_keys
        ],
        "workspaces": [{"id": workspace.id, "name": workspace.name} for workspace in report.workspaces],
        "allocation_rows": [
            {
                "date": row.date,
                "api_key_id": row.api_key_id,
                "workspace_id": row.workspace_id,
                "model": row.model,
                "service_tier": row.service_tier,
                "uncached_input_tokens": row.uncached_input_tokens,
                "cache_creation_1h_tokens": row.cache_creation_1h_tokens,
                "cache_creation_5m_tokens": row.cache_creation_5m_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "output_tokens": row.output_tokens,
                "web_search_requests": row.web_search_requests,
                "input_tokens": row.input_tokens,
                "total_tokens": row.total_tokens,
                "allocated_cost_usd": str(row.allocated_cost_usd),
            }
            for row in allocation.rows
        ],
        "claude_code_rows": [
            {
                "date": row.date,
                "actor": row.actor,
                "actor_type": row.actor_type,
                "customer_type": row.customer_type,
                "terminal": row.terminal_type,
                "models": row.models,
                "sessions": row.sessions,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cache_creation_tokens": row.cache_creation_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "total_tokens": row.total_tokens,
                "estimated_cost_usd": _format_usd(row.estimated_cost_usd),
            }
            for row in report.usage_rows
        ],
        "cost_rows": [
            {
                "date": row.date,
                "workspace_id": row.workspace_id,
                "description": row.description,
                "model": row.model,
                "cost_type": row.cost_type,
                "token_type": row.token_type,
                "amount_usd": _format_usd(row.amount_usd),
            }
            for row in report.cost_rows
        ],
    }


def _analysis_sections(
    report_data: dict[str, Any],
    workspace_id: str,
    api_key_id: str,
    model: str,
    environment: str,
    client_id: str | int,
    group_by: str,
    chart_metric: str = "usage",
) -> tuple[html.Div | dbc.Row, go.Figure, html.Div]:
    rows = _enriched_allocation_rows(report_data)
    filtered_rows = _filter_allocation_rows(
        rows,
        workspace_id=workspace_id,
        api_key_id=api_key_id,
        model=model,
        environment=environment,
        client_id=client_id,
    )
    input_tokens = sum(int(row["input_tokens"]) for row in filtered_rows)
    output_tokens = sum(int(row["output_tokens"]) for row in filtered_rows)
    web_searches = sum(int(row["web_search_requests"]) for row in filtered_rows)
    allocated_cost = sum((_decimal(row["allocated_cost_usd"]) for row in filtered_rows), Decimal("0"))
    disclaimer = _allocation_disclaimer(report_data)

    if not filtered_rows:
        return (
            html.Div(
                [
                    _analysis_kpis(0, 0, 0, Decimal("0"), disclaimer),
                    dbc.Alert("No usage matches the selected filters.", color="secondary"),
                ]
            ),
            _empty_over_time_figure(),
            html.Div(),
        )

    summary_rows = _aggregate_allocation_rows(filtered_rows, group_by)
    detail_rows = [_display_allocation_row(row) for row in filtered_rows]
    return (
        _analysis_kpis(input_tokens, output_tokens, web_searches, allocated_cost, disclaimer),
        _over_time_figure(filtered_rows, group_by, chart_metric),
        html.Div(
            [
                html.H3(f"Summary by {GROUP_LABELS[group_by].lower()}", className="h6"),
                data_table("anthropic-summary-table", summary_rows, 12),
                html.H3("Daily API-key detail", className="h6 mt-4"),
                data_table("anthropic-daily-detail-table", detail_rows, 15),
            ]
        ),
    )


def _empty_over_time_figure() -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(
        text="No usage matches the selected filters.",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
    )
    figure.update_layout(
        title="Usage over time",
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return apply_chart_theme(figure)


def _analysis_kpis(
    input_tokens: int,
    output_tokens: int,
    web_searches: int,
    allocated_cost: Decimal,
    cost_disclaimer: str,
) -> dbc.Row:
    return dbc.Row(
        [
            dbc.Col(kpi_card("Total tokens in", f"{input_tokens:,}"), md=6, xl=3),
            dbc.Col(kpi_card("Total tokens out", f"{output_tokens:,}"), md=6, xl=3),
            dbc.Col(kpi_card("Total web searches", f"{web_searches:,}"), md=6, xl=3),
            dbc.Col(
                kpi_card(
                    "Allocated billed cost",
                    _format_usd(allocated_cost),
                    tooltip=cost_disclaimer,
                    card_id="anthropic-allocated-billed-cost",
                ),
                md=6,
                xl=3,
            ),
        ],
        className="g-3 mb-4",
    )


def _enriched_allocation_rows(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    key_names = {key["id"]: key["name"] for key in report_data.get("api_keys", [])}
    workspace_names = {workspace["id"]: workspace["name"] for workspace in report_data.get("workspaces", [])}
    assignments = {
        assignment.api_key_id: assignment for assignment in AnthropicAssignmentRepository().list_assignments()
    }
    rows: list[dict[str, Any]] = []
    for raw_row in report_data.get("allocation_rows", []):
        row = dict(raw_row)
        assignment = assignments.get(row["api_key_id"])
        row.update(
            {
                "api_key_name": key_names.get(row["api_key_id"], row["api_key_id"]),
                "workspace_name": workspace_names.get(row["workspace_id"], row["workspace_id"]),
                "environment": assignment.environment if assignment else UNASSIGNED_VALUE,
                "client_id": assignment.client_id if assignment else None,
                "client_code": assignment.client_code if assignment else "Unassigned",
                "client_name": assignment.client_name if assignment else "Unassigned",
            }
        )
        rows.append(row)
    return rows


def _filter_allocation_rows(
    rows: list[dict[str, Any]],
    *,
    workspace_id: str,
    api_key_id: str,
    model: str,
    environment: str,
    client_id: str | int,
) -> list[dict[str, Any]]:
    selected_client = str(client_id)
    return [
        row
        for row in rows
        if (workspace_id == ALL_FILTER_VALUE or row["workspace_id"] == workspace_id)
        and (api_key_id == ALL_FILTER_VALUE or row["api_key_id"] == api_key_id)
        and (model == ALL_FILTER_VALUE or row["model"] == model)
        and (environment == ALL_FILTER_VALUE or row["environment"] == environment)
        and (
            selected_client == ALL_FILTER_VALUE
            or (selected_client == UNASSIGNED_VALUE and row["client_id"] is None)
            or str(row["client_id"]) == selected_client
        )
    ]


def _aggregate_allocation_rows(rows: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "uncached_input_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "web_search_requests": 0,
            "allocated_cost_usd": Decimal("0"),
        }
    )
    for row in rows:
        label = _group_label(row, group_by)
        total = totals[label]
        total["uncached_input_tokens"] += int(row["uncached_input_tokens"])
        total["cache_creation_tokens"] += int(row["cache_creation_1h_tokens"]) + int(row["cache_creation_5m_tokens"])
        total["cache_read_tokens"] += int(row["cache_read_tokens"])
        total["output_tokens"] += int(row["output_tokens"])
        total["total_tokens"] += int(row["total_tokens"])
        total["web_search_requests"] += int(row["web_search_requests"])
        total["allocated_cost_usd"] += _decimal(row["allocated_cost_usd"])
    return [
        {
            GROUP_LABELS[group_by].lower().replace(" ", "_"): label,
            **{key: value for key, value in total.items() if key != "allocated_cost_usd"},
            "allocated_cost_usd": _format_usd(total["allocated_cost_usd"]),
        }
        for label, total in sorted(totals.items())
    ]


def _display_allocation_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": row["date"],
        "api_key": row["api_key_name"],
        "environment": row["environment"].title(),
        "client": row["client_name"],
        "workspace": row["workspace_name"],
        "model": row["model"],
        "uncached_input_tokens": row["uncached_input_tokens"],
        "cache_creation_1h_tokens": row["cache_creation_1h_tokens"],
        "cache_creation_5m_tokens": row["cache_creation_5m_tokens"],
        "cache_read_tokens": row["cache_read_tokens"],
        "output_tokens": row["output_tokens"],
        "web_search_requests": row["web_search_requests"],
        "total_tokens": row["total_tokens"],
        "allocated_cost_usd": _format_usd(_decimal(row["allocated_cost_usd"])),
    }


def _token_usage_figure(rows: list[dict[str, Any]], group_by: str):
    chart_rows = [
        {
            "date": row["date"],
            "group": _group_label(row, group_by),
            "tokens": int(row["total_tokens"]),
        }
        for row in rows
    ]
    frame = pd.DataFrame(chart_rows).groupby(["date", "group"], as_index=False)["tokens"].sum()
    figure = px.bar(
        frame,
        x="date",
        y="tokens",
        color="group",
        barmode="stack",
        title="Token usage over time",
        labels={"date": "Date (UTC)", "tokens": "Tokens", "group": GROUP_LABELS[group_by]},
    )
    figure.update_layout(hovermode="x unified", legend_title_text=GROUP_LABELS[group_by])
    chronological_dates = sorted(frame["date"].unique())
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=chronological_dates)
    return apply_chart_theme(figure)


def _cost_over_time_figure(rows: list[dict[str, Any]], group_by: str):
    chart_rows = [
        {
            "date": row["date"],
            "group": _group_label(row, group_by),
            "cost_usd": float(_decimal(row["allocated_cost_usd"])),
        }
        for row in rows
    ]
    frame = pd.DataFrame(chart_rows).groupby(["date", "group"], as_index=False)["cost_usd"].sum()
    figure = px.bar(
        frame,
        x="date",
        y="cost_usd",
        color="group",
        barmode="stack",
        title="Allocated cost over time",
        labels={"date": "Date (UTC)", "cost_usd": "Cost (USD)", "group": GROUP_LABELS[group_by]},
    )
    figure.update_traces(hovertemplate="$%{y:,.4f} USD<extra>%{fullData.name}</extra>")
    figure.update_layout(hovermode="x unified", legend_title_text=GROUP_LABELS[group_by])
    figure.update_yaxes(tickprefix="$", tickformat=",.2f")
    chronological_dates = sorted(frame["date"].unique())
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=chronological_dates)
    return apply_chart_theme(figure)


def _over_time_figure(rows: list[dict[str, Any]], group_by: str, chart_metric: str):
    if chart_metric == "cost":
        return _cost_over_time_figure(rows, group_by)
    return _token_usage_figure(rows, group_by)


def _group_label(row: dict[str, Any], group_by: str) -> str:
    if group_by == "api_key":
        return str(row["api_key_name"])
    if group_by == "client":
        return str(row["client_name"])
    if group_by == "environment":
        return str(row["environment"]).title()
    return str(row["model"])


def _allocation_disclaimer(report_data: dict[str, Any]) -> str:
    billed = _decimal(report_data.get("billed_cost_usd"))
    allocated = _decimal(report_data.get("allocated_cost_usd"))
    unallocated = _decimal(report_data.get("unallocated_cost_usd"))
    return (
        "Anthropic does not report billed cost by API key. Costs are allocated proportionally by daily "
        f"workspace, model and usage. Billed: {_format_usd(billed)}; allocated: {_format_usd(allocated)}; "
        f"unallocated: {_format_usd(unallocated)}."
    )


def _report_filter_options(report_data: dict[str, Any], clients: list[Any]) -> dict[str, list[dict[str, Any]]]:
    workspace_names = {workspace["id"]: workspace["name"] for workspace in report_data.get("workspaces", [])}
    key_names = {key["id"]: key["name"] for key in report_data.get("api_keys", [])}
    rows = report_data.get("allocation_rows", [])
    workspace_ids = sorted({row["workspace_id"] for row in rows})
    api_key_ids = sorted({row["api_key_id"] for row in rows} | set(key_names))
    models = sorted({row["model"] for row in rows})
    return {
        "workspaces": [
            {"label": workspace_names.get(workspace_id, workspace_id), "value": workspace_id}
            for workspace_id in workspace_ids
        ],
        "api_keys": [
            {"label": key_names.get(api_key_id, api_key_id), "value": api_key_id} for api_key_id in api_key_ids
        ],
        "models": [{"label": model, "value": model} for model in models],
        "environments": [
            {"label": environment.title(), "value": environment}
            for environment in [*ENVIRONMENT_SOURCES, UNASSIGNED_VALUE]
        ],
        "clients": [{"label": f"{client.name} ({client.client_code})", "value": str(client.id)} for client in clients]
        + [{"label": "Unassigned", "value": UNASSIGNED_VALUE}],
    }


def _filter_control(
    label: str,
    component_id: str,
    options: list[dict[str, Any]],
    *,
    value: str = ALL_FILTER_VALUE,
    include_all: bool = True,
) -> html.Div:
    select_options = ([{"label": "All", "value": ALL_FILTER_VALUE}] if include_all else []) + options
    return html.Div(
        [
            dbc.Label(label, html_for=component_id, className="small mb-1"),
            dcc.Dropdown(
                id=component_id,
                options=select_options,
                value=value,
                clearable=False,
                searchable=True,
                style={"minWidth": "190px"},
            ),
        ]
    )


def _chart_metric_control() -> html.Div:
    return html.Div(
        [
            dbc.Label("View", html_for="anthropic-chart-metric", className="small mb-0"),
            dbc.RadioItems(
                id="anthropic-chart-metric",
                options=[
                    {"label": "Usage", "value": "usage"},
                    {"label": "Cost", "value": "cost"},
                ],
                value="usage",
                inline=True,
                persistence=True,
                persistence_type="session",
                className="btn-group anthropic-chart-toggle",
                input_class_name="btn-check",
                label_class_name="btn btn-outline-primary",
                label_checked_class_name="active",
            ),
        ],
        className="anthropic-chart-toolbar",
    )


def _assignment_rows(report_data: dict[str, Any], clients: list[Any]) -> list[dict[str, Any]]:
    assignments = {
        assignment.api_key_id: assignment for assignment in AnthropicAssignmentRepository().list_assignments()
    }
    workspace_names = {workspace["id"]: workspace["name"] for workspace in report_data.get("workspaces", [])}
    metadata = {key["id"]: key for key in report_data.get("api_keys", [])}
    usage_key_ids = {row["api_key_id"] for row in report_data.get("allocation_rows", [])}
    known_client_ids = {client.id for client in clients}
    rows: list[dict[str, Any]] = []
    for api_key_id in sorted(set(metadata) | usage_key_ids):
        if api_key_id == "Not attributed":
            continue
        key = metadata.get(api_key_id, {})
        assignment = assignments.get(api_key_id)
        key_name = key.get("name", api_key_id)
        rows.append(
            {
                "api_key_id": api_key_id,
                "api_key_name": key_name,
                "status": key.get("status", "unknown"),
                "workspace": workspace_names.get(key.get("workspace_id"), key.get("workspace_id", "Unknown")),
                "environment": assignment.environment if assignment else _suggest_environment(key_name),
                "client_id": assignment.client_id if assignment and assignment.client_id in known_client_ids else None,
            }
        )
    return rows


def _assignment_commands(rows: list[dict[str, Any]]) -> list[AnthropicKeyAssignmentCommand]:
    commands: list[AnthropicKeyAssignmentCommand] = []
    for row in rows:
        api_key_id = str(row.get("api_key_id") or "")
        client_id = row.get("client_id")
        if client_id in (None, ""):
            commands.append(AnthropicKeyAssignmentCommand(api_key_id, None, None))
            continue
        commands.append(
            AnthropicKeyAssignmentCommand(
                api_key_id=api_key_id,
                environment=str(row.get("environment") or ""),
                client_id=int(client_id),
            )
        )
    return commands


def _suggest_environment(api_key_name: str) -> str:
    normalized = api_key_name.lower()
    if "prod" in normalized:
        return "production"
    if "stage" in normalized or "staging" in normalized:
        return "staging"
    if "internal" in normalized:
        return "internal"
    return "development"


def _raw_report_details(report_data: dict[str, Any]) -> html.Div:
    claude_rows = report_data.get("claude_code_rows", [])
    cost_rows = report_data.get("cost_rows", [])
    return html.Div(
        [
            html.H4("Claude Code analytics by actor", className="h6 mt-3"),
            (
                data_table("claude-usage-table", claude_rows, 15)
                if claude_rows
                else dbc.Alert("No Claude Code actor analytics were returned for this range.", color="secondary")
            ),
            html.H4("Anthropic billed cost lines", className="h6 mt-4"),
            (
                data_table("claude-cost-table", cost_rows, 15)
                if cost_rows
                else dbc.Alert("No billed costs were returned for this range.", color="secondary")
            ),
        ]
    )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _format_usd(value: Decimal) -> str:
    return f"${value:,.2f} USD"


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
