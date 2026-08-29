import calendar
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from app.components.chart_theme import DEFAULT_PLOTLY_COLORWAY, apply_chart_theme
from app.components.charts import bar_chart
from app.components.tables import data_table, status_cell_styles, table_data_styles
from app.data.cost_repository import (
    CostCommand,
    CostManagementError,
    CostRepository,
    MetadataCommand,
)
from app.data.repositories import SeedRepository
from app.utils.currency import format_mxn

RECORD_TYPE_OPTIONS = ("actual", "estimate")


def layout():
    repo = SeedRepository()
    available_months = repo.available_months()
    selected_month = _default_month(available_months)
    selected_year = selected_month[:4]
    return html.Div(
        [
            dcc.Store(id="costs-refresh", data=0),
            dcc.Store(id="costs-action"),
            dcc.Store(id="costs-expected-updated-at"),
            dcc.Store(id="costs-selected-row-id"),
            html.Div(
                [
                    html.H1("Costs", className="h3 mb-0"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    dbc.Label("Year", html_for="costs-year-filter", className="small mb-1"),
                                    dcc.Dropdown(
                                        id="costs-year-filter",
                                        options=_year_options(available_months),
                                        value=selected_year,
                                        clearable=False,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                className="cost-period-year",
                            ),
                            html.Div(
                                [
                                    dbc.Label("Month", html_for="costs-month-filter", className="small mb-1"),
                                    dcc.Dropdown(
                                        id="costs-month-filter",
                                        options=_month_options(available_months, selected_year),
                                        value=selected_month,
                                        clearable=False,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                className="cost-period-month",
                            ),
                        ],
                        className="cost-period-filters",
                    ),
                ],
                className="costs-page-header",
            ),
            html.P(
                "Monthly and annual operating cost overview.",
                className="text-muted",
            ),
            html.Div(id="costs-dashboard-content", children=_dashboard_content(selected_month)),
            html.Details(
                [
                    html.Summary("Costs Table", className="h5"),
                    html.Div(
                        [
                            dbc.Button("Add cost", id="cost-add", color="primary"),
                            dbc.Button("Edit metadata", id="cost-edit", outline=True, disabled=True),
                            dbc.Button("Change cost", id="cost-change", outline=True, disabled=True),
                            dbc.Button("End cost", id="cost-end", outline=True, disabled=True),
                            dbc.Button("Deactivate", id="cost-deactivate", color="danger", outline=True, disabled=True),
                            dbc.Button("Reactivate", id="cost-reactivate", outline=True, disabled=True),
                            html.Div(
                                [
                                    dbc.Label("Status", html_for="cost-status-filter", className="visually-hidden"),
                                    dcc.Dropdown(
                                        id="cost-status-filter",
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
                    dbc.Alert(id="cost-management-message", is_open=False, dismissable=True),
                    dbc.Card(
                        dbc.CardBody(
                            data_table(
                                "costs-table",
                                _catalog_rows(repo),
                                15,
                                sort_by=[{"column_id": "updated_at", "direction": "desc"}],
                                excluded_columns=["cost_key", "created_at", "updated_at_raw"],
                            )
                        ),
                        className="content-card",
                    ),
                ],
                open=True,
            ),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="cost-action-title"), close_button=False),
                    dbc.ModalBody(
                        [
                            dbc.Alert(id="cost-action-error", color="danger", is_open=False),
                            html.Div(id="cost-action-body"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button("Cancel", id="cost-action-cancel", outline=True),
                            dbc.Button("Save", id="cost-action-submit", color="primary"),
                        ]
                    ),
                ],
                id="cost-action-modal",
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
        Output("costs-year-filter", "options"),
        Output("costs-month-filter", "options"),
        Output("costs-month-filter", "value"),
        Input("costs-year-filter", "value"),
        Input("costs-refresh", "data"),
        State("costs-month-filter", "value"),
    )
    def update_month_options(year: str, _refresh: int, selected_month: str | None):
        available_months = SeedRepository().available_months()
        available_years = {option["value"] for option in _year_options(available_months)}
        if year not in available_years:
            year = sorted(available_years)[-1]
        months = _months_for_year(available_months, year)
        if selected_month not in months:
            selected_month = months[-1]
        return _year_options(available_months), _month_options(available_months, year), selected_month

    @app.callback(
        Output("costs-dashboard-content", "children"),
        Input("costs-month-filter", "value"),
        Input("costs-refresh", "data"),
    )
    def update_dashboard(selected_month: str | None, _refresh: int):
        available_months = SeedRepository().available_months()
        return _dashboard_content(
            selected_month if selected_month in available_months else _default_month(available_months)
        )

    @app.callback(
        Output("costs-table", "data"),
        Output("costs-table", "active_cell"),
        Input("cost-status-filter", "value"),
        Input("costs-refresh", "data"),
    )
    def refresh_management_table(status: str, _refresh: int):
        return _catalog_rows(SeedRepository(), status), None

    @app.callback(
        Output("costs-selected-row-id", "data"),
        Output("costs-table", "style_data_conditional"),
        Input("costs-table", "active_cell"),
        Input("cost-status-filter", "value"),
        Input("costs-refresh", "data"),
    )
    def select_cost_row(active_cell: dict | None, _status: str, _refresh: int):
        if ctx.triggered_id != "costs-table":
            return None, _cost_table_styles(None)
        if not active_cell or active_cell.get("row_id") is None:
            return None, _cost_table_styles(None)
        selected_row_id = active_cell["row_id"]
        return selected_row_id, _cost_table_styles(selected_row_id)

    @app.callback(
        Output("cost-edit", "disabled"),
        Output("cost-change", "disabled"),
        Output("cost-end", "disabled"),
        Output("cost-deactivate", "disabled"),
        Output("cost-reactivate", "disabled"),
        Input("costs-selected-row-id", "data"),
        State("costs-table", "data"),
    )
    def enable_cost_actions(selected_row_id: int | None, table_rows: list[dict] | None):
        disabled = selected_row_id is None
        selected = _selected_cost(selected_row_id, table_rows)
        is_inactive = selected is not None and selected.get("status") == "inactive"
        return disabled, disabled, disabled, disabled or is_inactive, disabled or not is_inactive

    @app.callback(
        Output("cost-action-modal", "is_open"),
        Output("cost-action-title", "children"),
        Output("cost-action-body", "children"),
        Output("costs-action", "data"),
        Output("costs-expected-updated-at", "data"),
        Output("cost-action-error", "children"),
        Output("cost-action-error", "is_open"),
        Output("cost-management-message", "children"),
        Output("cost-management-message", "color"),
        Output("cost-management-message", "is_open"),
        Output("costs-refresh", "data"),
        Input("cost-add", "n_clicks"),
        Input("cost-edit", "n_clicks"),
        Input("cost-change", "n_clicks"),
        Input("cost-end", "n_clicks"),
        Input("cost-deactivate", "n_clicks"),
        Input("cost-reactivate", "n_clicks"),
        Input("cost-action-cancel", "n_clicks"),
        Input("cost-action-submit", "n_clicks"),
        State("costs-selected-row-id", "data"),
        State("costs-table", "data"),
        State("costs-action", "data"),
        State("costs-expected-updated-at", "data"),
        State({"type": "cost-field", "name": ALL}, "id"),
        State({"type": "cost-field", "name": ALL}, "value"),
        State("costs-refresh", "data"),
        prevent_initial_call=True,
        running=[(Output("cost-action-submit", "disabled"), True, False)],
    )
    def manage_cost(
        _add,
        _edit,
        _change,
        _end,
        _deactivate,
        _reactivate,
        _cancel,
        _submit,
        selected_row_id,
        table_rows,
        action,
        expected_updated_at,
        field_ids,
        field_values,
        refresh,
    ):
        defaults = (no_update,) * 11
        trigger = ctx.triggered_id
        if trigger == "cost-action-cancel":
            return False, no_update, no_update, None, None, no_update, False, no_update, no_update, False, no_update
        if trigger != "cost-action-submit":
            action = {
                "cost-add": "add",
                "cost-edit": "edit",
                "cost-change": "change",
                "cost-end": "end",
                "cost-deactivate": "deactivate",
                "cost-reactivate": "reactivate",
            }.get(trigger)
            selected = _selected_cost(selected_row_id, table_rows) if action != "add" else None
            if action != "add" and selected is None:
                return (
                    False,
                    no_update,
                    no_update,
                    None,
                    None,
                    no_update,
                    False,
                    "Select one cost record first.",
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
        selected = _selected_cost(selected_row_id, table_rows) if action != "add" else None
        fields_by_name = {item["name"]: value for item, value in zip(field_ids, field_values, strict=True)}
        try:
            _execute_cost_action(action, selected, fields_by_name, expected_updated_at)
        except CostManagementError as exc:
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
        labels = {
            "add": "created",
            "edit": "updated",
            "change": "versioned",
            "end": "ended",
            "deactivate": "deactivated",
            "reactivate": "reactivated",
        }
        return (
            False,
            no_update,
            no_update,
            None,
            None,
            no_update,
            False,
            f"Cost {labels[action]} successfully.",
            "success",
            True,
            (refresh or 0) + 1,
        )

    @app.callback(
        Output("costs-selected-month-dynamic", "children"),
        Input("costs-selected-month", "n_clicks"),
        State("costs-month-filter", "value"),
    )
    def toggle_selected_month_split(n_clicks: int | None, selected_month: str):
        repo = SeedRepository()
        rows = _year_cost_rows(repo, int(selected_month[:4]))
        split = _summarize_cost_rows([row for row in rows if row["month"] == selected_month])
        return _cost_summary_content(_month_card_title(selected_month), split, _show_split(n_clicks))

    @app.callback(
        Output("costs-selected-year-dynamic", "children"),
        Input("costs-selected-year", "n_clicks"),
        State("costs-month-filter", "value"),
    )
    def toggle_selected_year_split(n_clicks: int | None, selected_month: str):
        selected_year = int(selected_month[:4])
        split = _summarize_cost_rows(_year_cost_rows(SeedRepository(), selected_year))
        return _cost_summary_content(
            f"Total Cost - {selected_year}",
            split,
            _show_split(n_clicks),
        )


def _dashboard_content(selected_month: str) -> html.Div:
    repo = SeedRepository()
    selected_year = int(selected_month[:4])
    year_rows = _year_cost_rows(repo, selected_year)
    month_split = _summarize_cost_rows([row for row in year_rows if row["month"] == selected_month])
    year_split = _summarize_cost_rows(year_rows)
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        _cost_summary_card(
                            _month_card_title(selected_month),
                            month_split,
                            "costs-selected-month",
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        _cost_summary_card(
                            f"Total Cost - {selected_year}",
                            year_split,
                            "costs-selected-year",
                        ),
                        md=6,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(
                        figure=_year_cost_chart(year_rows, selected_year),
                        config={"displayModeBar": False},
                    )
                ),
                className="content-card mb-4",
            ),
            html.H2(f"Realized Costs for {selected_month}", className="h5"),
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Graph(figure=bar_chart(repo.cost_by_service(selected_month), "Costs by Service Line")),
                        md=4,
                    ),
                    dbc.Col(
                        dcc.Graph(figure=bar_chart(repo.cost_by_provider(selected_month), "Costs by Provider")),
                        md=4,
                    ),
                    dbc.Col(
                        dcc.Graph(figure=bar_chart(repo.cost_by_category(selected_month), "Costs by Category")),
                        md=4,
                    ),
                ],
                className="mb-3",
            ),
            dbc.Card(
                dbc.CardBody(data_table("monthly-costs-table", _monthly_cost_rows(repo, selected_month), 10)),
                className="content-card mb-4",
            ),
        ]
    )


def _year_cost_rows(repo: SeedRepository, year: int) -> list[dict]:
    year_prefix = f"{year}-"
    return [row for row in repo.cost_history() if row["month"].startswith(year_prefix)]


def _default_month(available_months: list[str]) -> str:
    current_month = date.today().strftime("%Y-%m")
    return current_month if current_month in available_months else available_months[-1]


def _year_options(available_months: list[str]) -> list[dict[str, str]]:
    years = sorted({month[:4] for month in available_months})
    return [{"label": year, "value": year} for year in years]


def _months_for_year(available_months: list[str], year: str) -> list[str]:
    months = [month for month in available_months if month.startswith(f"{year}-")]
    if not months:
        raise ValueError(f"No cost months are available for {year}")
    return months


def _month_options(available_months: list[str], year: str) -> list[dict[str, str]]:
    return [
        {"label": calendar.month_name[int(month[-2:])], "value": month}
        for month in _months_for_year(available_months, year)
    ]


def _month_card_title(selected_month: str) -> str:
    year, month = (int(part) for part in selected_month.split("-"))
    return f"Total Cost - {calendar.month_name[month]} {year}"


def _catalog_rows(repo: SeedRepository, status: str = "all") -> list[dict]:
    items = repo.cost_items()
    if status == "active":
        items = [item for item in items if item.enabled]
    elif status == "inactive":
        items = [item for item in items if not item.enabled]
    valuations = repo.cost_catalog_valuations(items)
    return [
        {
            "id": f"{item.id:04d}",
            "cost_key": item.cost_key,
            "name": item.name,
            "status": (
                "inactive"
                if not item.enabled
                else ("ended" if item.end_date and item.end_date < date.today() else "active")
            ),
            "category": item.category,
            "service_line": item.service_line or "Shared",
            "provider": item.provider or "",
            "cost_type": item.cost_type,
            "frequency": item.billing_frequency,
            "charge_basis": item.charge_basis,
            "quantity": f"{item.quantity:,.0f}",
            "unit": item.unit,
            "unit_cost": f"{item.display_unit_cost:,.2f}",
            "currency": item.display_currency,
            "fx_rate": f"{valuations[item.id].fx_rate:,.4f}" if valuations[item.id].fx_rate is not None else "N/A",
            "fx_date": valuations[item.id].fx_rate_date.isoformat() if valuations[item.id].fx_rate_date else "",
            "valuation_date": valuations[item.id].valuation_date.isoformat(),
            "fx_status": (
                "Provisional" if valuations[item.id].fx_rate is not None and valuations[item.id].provisional else ""
            ),
            "base_amount": f"${item.quantity * valuations[item.id].unit_cost_mxn:,.2f} MXN",
            "start_date": item.start_date.isoformat() if item.start_date else "",
            "end_date": item.end_date.isoformat() if item.end_date else "",
            "record_type": item.record_type,
            "updated_at": _format_utc(item.updated_at),
            "notes": item.notes or "",
            "created_at": _format_utc(item.created_at),
            "updated_at_raw": item.updated_at.isoformat() if item.updated_at else "",
        }
        for item in items
    ]


def _format_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _selected_cost(selected_row_id: int | str | None, table_rows: list[dict] | None) -> dict | None:
    if selected_row_id is None or not table_rows:
        return None
    return next((row for row in table_rows if row.get("id") == selected_row_id), None)


def _cost_table_styles(selected_row_id: str | None) -> list[dict]:
    styles = table_data_styles()
    if selected_row_id is not None:
        row_filter = f'{{id}} = "{selected_row_id}"'
        styles.extend(
            [
                {
                    "if": {"filter_query": row_filter},
                    "backgroundColor": "var(--color-surface-soft)",
                    "borderTop": "2px solid var(--color-primary)",
                    "borderBottom": "2px solid var(--color-primary)",
                    "color": "var(--color-text)",
                    "fontWeight": "600",
                },
                {
                    "if": {"filter_query": row_filter, "column_id": "id"},
                    "borderLeft": "4px solid var(--color-primary)",
                },
            ]
        )
    styles.extend(status_cell_styles("status"))
    return styles


def _field(name: str, label: str, value=None, *, kind: str = "text", options=None, required: bool = False):
    field_id = {"type": "cost-field", "name": name}
    html_id = json.dumps(field_id, separators=(",", ":"))
    if options is not None:
        control = dcc.Dropdown(
            id=field_id,
            options=[{"label": option.replace("_", " ").title(), "value": option} for option in options],
            value=value,
            clearable=False,
        )
    elif kind == "textarea":
        control = dbc.Textarea(id=field_id, value=value or "", rows=3)
    else:
        control = dbc.Input(id=field_id, value=value, type=kind, required=required)
    return html.Div([dbc.Label(label, html_for=html_id, className="form-label"), control], className="mb-3")


def _action_title(action: str) -> str:
    return {
        "add": "Add cost",
        "edit": "Edit non-financial metadata",
        "change": "Create a new cost version",
        "end": "End cost",
        "deactivate": "Deactivate mistaken cost",
        "reactivate": "Reactivate cost record",
    }[action]


def _action_form(action: str, selected: dict | None):
    selected = selected or {}
    if action == "edit":
        return html.Div(
            [
                dbc.Alert(
                    "Start and end dates are lifecycle corrections. Changing them can alter which reporting "
                    "periods include this record.",
                    color="warning",
                ),
                _field("name", "Name", selected.get("name"), required=True),
                _field("provider", "Provider", selected.get("provider")),
                _field("category", "Category", selected.get("category"), required=True),
                _field("service_line", "Service line", selected.get("service_line")),
                _field("start_date", "Start date", selected.get("start_date"), kind="date"),
                _field("end_date", "End date", selected.get("end_date"), kind="date"),
                _field("notes", "Notes", selected.get("notes"), kind="textarea"),
            ]
        )
    if action == "end":
        return html.Div(
            [
                dbc.Alert(
                    "Use an end date for an ordinary cancellation. The record stays enabled "
                    "for historical calculations.",
                    color="info",
                ),
                _field("end_date", "End date", selected.get("end_date"), kind="date", required=True),
            ]
        )
    if action == "deactivate":
        return html.Div(
            [
                html.P([html.Strong(selected.get("name", "")), html.Br(), html.Code(selected.get("cost_key", ""))]),
                html.P(
                    f"Version effective from {selected.get('start_date') or 'unspecified date'} will remain stored."
                ),
                dbc.Alert(
                    "Deactivation excludes this record from economic calculations. Use it only for a mistaken "
                    "or invalid record; there is no delete action.",
                    color="warning",
                ),
            ]
        )
    if action == "reactivate":
        return html.Div(
            [
                html.P([html.Strong(selected.get("name", "")), html.Br(), f"Record ID {selected.get('id')}"]),
                dbc.Alert(
                    "Reactivation restores this stored record to economic calculations without changing its dates. "
                    "An ended record will return to Ended status.",
                    color="info",
                ),
            ]
        )
    common = (
        []
        if action == "change"
        else [
            _field("name", "Name", selected.get("name"), required=True),
            _field("provider", "Provider", selected.get("provider")),
            _field("category", "Category", selected.get("category"), required=True),
            _field("service_line", "Service line", selected.get("service_line")),
        ]
    )
    if action == "change":
        common.append(
            dbc.Alert(
                f"A new historical version will be created. Previous base amount: {selected.get('base_amount', '')}.",
                color="info",
            )
        )
        common.append(_field("effective_from", "Effective from", kind="date", required=True))
    record_type = selected.get("record_type", "actual")
    if record_type not in RECORD_TYPE_OPTIONS:
        record_type = "estimate"
    common.extend(
        [
            _field(
                "charge_basis",
                "Charge basis",
                selected.get("charge_basis", "flat"),
                options=["flat", "per_user", "usage"],
            ),
            _field("quantity", "Quantity", selected.get("quantity", "1"), required=True),
            _field("unit_cost", "Unit cost", selected.get("unit_cost", "0"), required=True),
            _field("currency", "Currency", selected.get("currency", "MXN"), options=["MXN", "USD"]),
            _field("unit", "Unit", selected.get("unit", "month"), required=True),
            _field(
                "billing_frequency",
                "Billing frequency",
                selected.get("frequency", "monthly"),
                options=["monthly", "annual", "usage", "once"],
            ),
            _field(
                "record_type",
                "Record type",
                record_type,
                options=RECORD_TYPE_OPTIONS,
            ),
        ]
    )
    if action == "add":
        common.extend(
            [
                _field("start_date", "Start date", date.today().isoformat(), kind="date", required=True),
                _field("end_date", "Optional end date", kind="date"),
                _field("notes", "Notes", kind="textarea"),
            ]
        )
    return html.Div(common)


def _execute_cost_action(action: str, selected: dict | None, values: dict, expected_updated_at: str | None) -> None:
    repository = CostRepository()
    if action == "add":
        repository.create_cost(
            CostCommand(
                name=values.get("name"),
                provider=values.get("provider"),
                category=values.get("category"),
                service_line=values.get("service_line"),
                cost_type=_cost_type_for_frequency(values.get("billing_frequency")),
                charge_basis=values.get("charge_basis"),
                quantity=values.get("quantity"),
                unit_cost=values.get("unit_cost"),
                currency=values.get("currency"),
                unit=values.get("unit"),
                billing_frequency=values.get("billing_frequency"),
                start_date=values.get("start_date"),
                end_date=values.get("end_date"),
                record_type=values.get("record_type"),
                notes=values.get("notes"),
            )
        )
        return
    if selected is None or not expected_updated_at:
        raise CostManagementError("The selected record is no longer available. Refresh and try again.")
    record_id = int(selected["id"])
    if action == "edit":
        repository.update_cost_metadata(
            record_id,
            MetadataCommand(
                name=values.get("name"),
                provider=values.get("provider"),
                category=values.get("category"),
                service_line=values.get("service_line"),
                notes=values.get("notes"),
                start_date=values.get("start_date"),
                end_date=values.get("end_date"),
            ),
            expected_updated_at,
        )
    elif action == "change":
        changes = {
            key: values.get(key)
            for key in (
                "charge_basis",
                "quantity",
                "unit_cost",
                "currency",
                "unit",
                "billing_frequency",
                "record_type",
            )
        }
        changes["cost_type"] = _cost_type_for_frequency(values.get("billing_frequency"))
        repository.create_cost_version(record_id, changes, values.get("effective_from"), expected_updated_at)
    elif action == "end":
        repository.end_cost(record_id, values.get("end_date"), expected_updated_at)
    elif action == "deactivate":
        repository.deactivate_cost(record_id, expected_updated_at)
    elif action == "reactivate":
        repository.reactivate_cost(record_id, expected_updated_at)


def _cost_type_for_frequency(billing_frequency: str | None) -> str:
    return "variable" if billing_frequency == "usage" else "fixed"


def _monthly_cost_rows(repo: SeedRepository, selected_month: str) -> list[dict]:
    return [
        {
            "cost_key": cost.cost_key,
            "name": cost.name,
            "provider": cost.provider or "",
            "category": cost.category,
            "service_line": cost.service_line,
            "cost_type": cost.cost_type,
            "quantity": f"{cost.quantity:,.0f}",
            "unit_cost": f"{cost.unit_cost:,.2f}",
            "currency": cost.currency,
            "fx_rate": f"{cost.fx_rate:,.4f}" if cost.fx_rate is not None else "",
            "fx_date": cost.fx_rate_date.isoformat() if cost.fx_rate_date else "",
            "valuation_date": cost.valuation_date.isoformat() if cost.fx_rate is not None else "",
            "fx_status": "Provisional" if cost.provisional_fx and cost.fx_rate is not None else "",
            "unit": cost.unit,
            "amount": format_mxn(cost.amount),
            "start_date": cost.start_date.isoformat() if cost.start_date else "",
            "end_date": cost.end_date.isoformat() if cost.end_date else "",
        }
        for cost in repo.monthly_cost_amounts(selected_month)
    ]


def _summarize_cost_rows(rows: list[dict]) -> dict[str, Decimal]:
    fixed = sum((row["fixed"] + row["one_time"] for row in rows), Decimal("0"))
    variable = sum((row["variable"] for row in rows), Decimal("0"))
    return {"fixed": fixed, "variable": variable, "total": fixed + variable}


def _cost_summary_card(title: str, split: dict[str, Decimal], card_id: str) -> html.Div:
    return html.Div(
        dbc.Card(
            dbc.CardBody(
                html.Div(
                    _cost_summary_content(title, split, show_split=False),
                    id=f"{card_id}-dynamic",
                )
            ),
            className="kpi-card h-100",
        ),
        className="cost-card-toggle h-100",
        id=card_id,
        n_clicks=0,
        tabIndex=0,
        role="button",
        **{"aria-label": f"{title}. Click to toggle fixed and variable cost split."},
    )


def _cost_summary_content(title: str, split: dict[str, Decimal], show_split: bool) -> list:
    content = [
        html.Div(title, className="kpi-label"),
        html.Div(format_mxn(split["total"]), className="kpi-value"),
    ]
    if show_split:
        content.extend(
            [
                html.Div(
                    [
                        html.Span("Fixed + one-time", className="text-muted"),
                        html.Strong(format_mxn(split["fixed"])),
                    ],
                    className="cost-split-row",
                ),
                html.Div(
                    [
                        html.Span("Variable", className="text-muted"),
                        html.Strong(format_mxn(split["variable"])),
                    ],
                    className="cost-split-row",
                ),
                html.Div("Click to hide split", className="kpi-subtitle mt-1"),
            ]
        )
    else:
        content.append(html.Div("Click for fixed / variable split", className="kpi-subtitle"))
    return content


def _show_split(n_clicks: int | None) -> bool:
    return bool(n_clicks and n_clicks % 2)


def _year_cost_chart(rows: list[dict], year: int):
    chart_rows = [
        {
            "month": row["month"],
            "cost_type": cost_type,
            "amount": float(amount),
        }
        for row in rows
        for cost_type, amount in (
            ("Fixed + one-time", row["fixed"] + row["one_time"]),
            ("Variable", row["variable"]),
        )
    ]

    frame = pd.DataFrame(chart_rows, columns=["month", "cost_type", "amount"])
    figure = px.bar(
        frame,
        x="month",
        y="amount",
        color="cost_type",
        barmode="stack",
        title=f"Monthly Costs in {year}",
        labels={"amount": "MXN", "month": "", "cost_type": "Cost type"},
        color_discrete_sequence=DEFAULT_PLOTLY_COLORWAY,
    )
    figure.update_layout(
        legend_title_text="",
        margin=dict(l=20, r=20, t=50, b=20),
        hovermode="closest",
    )
    figure.update_traces(hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>$%{y:,.2f} MXN<extra></extra>")
    figure.update_xaxes(type="category", tickformat="%Y-%m")
    figure.update_yaxes(tickprefix="$", separatethousands=True)
    return apply_chart_theme(figure, colorway=DEFAULT_PLOTLY_COLORWAY)
