"""Executive Summary grid definitions."""

import dash_ag_grid as dag

from app.components.tables import data_grid


def client_grid(table_id: str, rows: list[dict]) -> dag.AgGrid:
    columns = [
        {"field": "client", "headerName": "Client", "filter": "agTextColumnFilter", "minWidth": 170},
    ]
    for field, label in (
        ("revenue", "Revenue (MXN)"),
        ("variable_cost", "Variable cost (MXN)"),
        ("allocated_fixed_cost", "Allocated fixed cost (MXN)"),
        ("operating_margin", "Operating margin (MXN)"),
        ("operating_margin_percentage", "Operating margin (%)"),
    ):
        columns.append(
            {
                "field": field,
                "headerName": label,
                "type": "numericColumn",
                "cellDataType": "number",
                "filter": "agNumberColumnFilter",
                "minWidth": 150,
                "valueFormatter": {
                    "function": (
                        "valtehPercent(params)"
                        if field == "operating_margin_percentage"
                        else "valtehMoney(params, 'MXN', 2)"
                    )
                },
            }
        )
    return data_grid(
        table_id,
        rows,
        5,
        column_defs=columns,
        pagination=True,
        auto_height=True,
        empty_message="No clients match this view",
        class_name="executive-grid",
        default_col_def={
            "flex": 1,
        },
        dash_grid_options={"paginationPageSizeSelector": False},
    )
