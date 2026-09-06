from pathlib import Path

from app.components.tables import data_grid


def _column(grid, field):
    return next(column for column in grid.columnDefs if column["field"] == field)


def test_data_grid_infers_typed_columns_and_keeps_raw_numeric_values():
    rows = [
        {
            "client": "SAREMI",
            "amount_usd": -12.5,
            "margin_percentage": 0.25,
            "total_tokens": 1234,
            "usd_mxn_rate": 18.4725,
            "active": False,
            "invoice_date": "2026-08-31",
            "internal_id": 7,
        }
    ]

    grid = data_grid("typed-grid", rows, excluded_columns=("internal_id",))

    assert grid.rowData == rows
    assert _column(grid, "amount_usd")["valueFormatter"]["function"] == "valtehMoney(params, 'USD', 2)"
    assert _column(grid, "margin_percentage")["valueFormatter"]["function"] == "valtehPercent(params)"
    assert _column(grid, "total_tokens")["valueFormatter"]["function"] == "valtehInteger(params)"
    assert _column(grid, "usd_mxn_rate")["valueFormatter"]["function"] == "valtehDecimal(params, 4)"
    assert _column(grid, "active")["cellDataType"] == "boolean"
    assert _column(grid, "invoice_date")["cellDataType"] == "dateString"
    assert "internal_id" not in {column["field"] for column in grid.columnDefs}


def test_data_grid_configures_selection_sort_pagination_and_safe_empty_state():
    grid = data_grid(
        "selected-grid",
        [{"id": 11, "status": "active", "updated_at": "2026-08-31T12:00:00"}],
        page_size=12,
        selectable=True,
        row_id_field="id",
        initial_sort=[{"column_id": "updated_at", "direction": "desc"}],
        empty_message='<img src=x onerror="alert(1)">',
    )

    assert grid.getRowId == "params.data.id"
    assert grid.dangerously_allow_code is True
    assert grid.dashGridOptions["rowSelection"]["mode"] == "singleRow"
    assert grid.dashGridOptions["paginationPageSizeSelector"] == [5, 10, 12, 15, 25, 50]
    assert _column(grid, "updated_at")["sort"] == "desc"
    assert "&lt;img" in grid.dashGridOptions["overlayNoRowsTemplate"]
    assert _column(grid, "status")["cellClass"] == {"function": "valtehStatusClass(params)"}


def test_data_grid_uses_community_select_editor_with_raw_dropdown_values():
    grid = data_grid(
        "assignment-grid",
        [{"client_id": 2}],
        dropdown={
            "client_id": {
                "options": [
                    {"label": "Unassigned", "value": ""},
                    {"label": "Client A (CLI-A)", "value": 2},
                ]
            }
        },
    )

    column = _column(grid, "client_id")
    assert column["cellEditor"] == "agSelectCellEditor"
    assert column["cellEditorParams"]["values"] == ["", 2]
    assert column["cellEditorParams"]["labels"]["2"] == "Client A (CLI-A)"
    assert column["valueFormatter"]["function"] == "valtehLookup(params)"


def test_read_only_grid_disables_row_selection_without_removing_keyboard_focus():
    grid = data_grid("read-only-grid", [{"name": "Example"}])

    selection = grid.dashGridOptions["rowSelection"]
    assert selection["mode"] == "singleRow"
    assert selection["enableClickSelection"] is False
    assert selection["isRowSelectable"] == {"function": "false"}


def test_application_has_no_legacy_dash_datatable_usage():
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py"))
    assert "dash_table" not in source
    assert "DataTable(" not in source
