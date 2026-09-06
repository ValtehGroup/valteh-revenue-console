"""Shared Dash AG Grid presentation helpers."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from html import escape
from typing import Any

import dash_ag_grid as dag

MONEY_COLUMN_TERMS = {"amount", "cost", "fee", "margin", "price", "revenue"}


def data_grid(
    grid_id: str,
    rows: list[dict[str, Any]],
    page_size: int = 10,
    *,
    column_defs: list[dict[str, Any]] | None = None,
    excluded_columns: Iterable[str] = (),
    column_options: dict[str, dict[str, Any]] | None = None,
    dropdown: dict[str, dict[str, Any]] | None = None,
    initial_sort: list[dict[str, str]] | None = None,
    currency: str = "MXN",
    editable: bool = False,
    selectable: bool = False,
    row_id_field: str | None = None,
    pagination: bool = True,
    auto_height: bool = True,
    height: str = "30rem",
    empty_message: str = "No data available",
    class_name: str = "",
    default_col_def: dict[str, Any] | None = None,
    dash_grid_options: dict[str, Any] | None = None,
) -> dag.AgGrid:
    """Build a themed Community grid while keeping raw values in ``rowData``."""
    options = column_options or {}
    dropdowns = dropdown or {}
    definitions = column_defs or _column_definitions(rows, excluded_columns, options, dropdowns, currency)
    _apply_initial_sort(definitions, initial_sort or [])

    grid_options: dict[str, Any] = {
        "theme": {"function": "valtehGridTheme(themeQuartz)"},
        "animateRows": False,
        "ensureDomOrder": True,
        "pagination": pagination,
        "paginationPageSize": page_size,
        "paginationPageSizeSelector": sorted({5, 10, 15, 25, 50, page_size}),
        "suppressMovableColumns": True,
        "suppressCellFocus": False,
        "tooltipShowDelay": 250,
        "rowSelection": {
            "mode": "singleRow",
            "checkboxes": False,
            "headerCheckbox": False,
            "enableClickSelection": False,
            "isRowSelectable": {"function": "false"},
        },
        "overlayNoRowsTemplate": f'<span class="grid-empty-message">{escape(empty_message)}</span>',
    }
    if auto_height:
        grid_options["domLayout"] = "autoHeight"
    if selectable:
        grid_options["rowSelection"] = {
            "mode": "singleRow",
            "checkboxes": False,
            "headerCheckbox": False,
            "enableClickSelection": True,
        }
    grid_options.update(dash_grid_options or {})

    base_column = {
        "sortable": True,
        "resizable": True,
        "filter": True,
        "floatingFilter": True,
        "wrapHeaderText": True,
        "autoHeaderHeight": True,
        "minWidth": 130,
        "flex": 1,
        "editable": editable,
    }
    base_column.update(default_col_def or {})
    style = {"width": "100%", "height": None if auto_height else height, "minHeight": "8rem"}
    component_options: dict[str, Any] = {
        "id": grid_id,
        "className": " ".join(part for part in ("valteh-grid", class_name) if part),
        "rowData": rows,
        "columnDefs": definitions,
        "defaultColDef": base_column,
        "dashGridOptions": grid_options,
        "dangerously_allow_code": True,
        "style": style,
    }
    if row_id_field:
        component_options["getRowId"] = f"params.data.{row_id_field}"
    return dag.AgGrid(**component_options)


def _column_definitions(
    rows: list[dict[str, Any]],
    excluded_columns: Iterable[str],
    options: dict[str, dict[str, Any]],
    dropdowns: dict[str, dict[str, Any]],
    currency: str,
) -> list[dict[str, Any]]:
    excluded = set(excluded_columns)
    fields = [field for field in rows[0] if field not in excluded] if rows else []
    return [_column_definition(field, rows, options.get(field, {}), dropdowns.get(field), currency) for field in fields]


def _column_definition(
    field: str,
    rows: list[dict[str, Any]],
    options: dict[str, Any],
    dropdown: dict[str, Any] | None,
    currency: str,
) -> dict[str, Any]:
    configured = dict(options)
    header_name = configured.pop("name", configured.pop("headerName", field.replace("_", " ").title()))
    configured.pop("presentation", None)
    definition: dict[str, Any] = {"field": field, "headerName": header_name, "tooltipField": field}
    sample = next((row.get(field) for row in rows if row.get(field) not in (None, "")), None)
    if isinstance(sample, bool):
        definition.update(cellDataType="boolean", filter="agTextColumnFilter")
        definition["valueFormatter"] = {"function": "valtehBoolean(params)"}
    elif isinstance(sample, (int, float, Decimal)) and not isinstance(sample, bool):
        definition.update(type="numericColumn", cellDataType="number", filter="agNumberColumnFilter")
        definition["valueFormatter"] = {"function": _numeric_formatter(field, currency)}
    elif _looks_like_iso_date(field, sample):
        definition.update(cellDataType="dateString", filter="agDateColumnFilter")
    else:
        definition.update(cellDataType="text", filter="agTextColumnFilter")

    if field in {"status", "client_status", "resolution_status"}:
        definition["cellClass"] = {"function": "valtehStatusClass(params)"}
    if dropdown is not None:
        choices = dropdown.get("options", [])
        definition.update(
            editable=True,
            cellEditor="agSelectCellEditor",
            cellEditorParams={
                "values": [choice.get("value") for choice in choices],
                "labels": {str(choice.get("value")): choice.get("label") for choice in choices},
            },
            valueFormatter={"function": "valtehLookup(params)"},
        )
    definition.update(configured)
    return definition


def _numeric_formatter(field: str, currency: str) -> str:
    terms = set(field.lower().split("_"))
    if "percentage" in terms or "multiplier" in terms:
        return "valtehPercent(params)"
    if ({"usd", "mxn"} <= terms) or "rate" in terms:
        return "valtehDecimal(params, 4)"
    if "usd" in terms and terms & MONEY_COLUMN_TERMS:
        return "valtehMoney(params, 'USD', 2)"
    if "mxn" in terms and terms & MONEY_COLUMN_TERMS:
        return "valtehMoney(params, 'MXN', 2)"
    if terms & MONEY_COLUMN_TERMS:
        return f"valtehMoney(params, '{currency}', 2)"
    if terms & {"clients", "documents", "requests", "tokens", "total", "usage"}:
        return "valtehInteger(params)"
    return "valtehNumber(params, 2)"


def _looks_like_iso_date(field: str, sample: Any) -> bool:
    return (
        (field.endswith("_date") or field in {"date", "timestamp"})
        and isinstance(sample, str)
        and len(sample) == 10
        and sample[4:5] == "-"
        and sample[7:8] == "-"
    )


def _apply_initial_sort(definitions: list[dict[str, Any]], sort_by: list[dict[str, str]]) -> None:
    order = {item.get("column_id", item.get("field")): item.get("direction", item.get("sort")) for item in sort_by}
    for definition in definitions:
        if definition.get("field") in order:
            definition["sort"] = "desc" if order[definition["field"]] == "desc" else "asc"
