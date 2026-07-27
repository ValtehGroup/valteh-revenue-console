from dash import dash_table

NUMERIC_COLUMN_TERMS = {
    "amount",
    "clients",
    "cost",
    "fee",
    "margin",
    "price",
    "quantity",
    "rate",
    "revenue",
    "total",
    "usage",
    "value",
}


def table_data_styles() -> list[dict]:
    return [
        {"if": {"row_index": "odd"}, "backgroundColor": "var(--color-row-alt)"},
        {
            "if": {"state": "active"},
            "backgroundColor": "var(--color-surface-soft)",
            "border": "1px solid var(--color-primary)",
            "color": "var(--color-text)",
        },
        {
            "if": {"state": "selected"},
            "backgroundColor": "var(--color-surface-soft)",
            "border": "1px solid var(--color-primary)",
            "color": "var(--color-text)",
        },
    ]


def status_cell_styles(column_id: str) -> list[dict]:
    return [
        {
            "if": {"filter_query": f'{{{column_id}}} = "active"', "column_id": column_id},
            "color": "var(--color-status-active)",
            "fontWeight": "700",
        },
        {
            "if": {"filter_query": f'{{{column_id}}} = "inactive"', "column_id": column_id},
            "color": "var(--color-danger)",
            "fontWeight": "700",
        },
    ]


def data_table(table_id: str, rows: list[dict], page_size: int = 10, **kwargs) -> dash_table.DataTable:
    excluded_columns = set(kwargs.pop("excluded_columns", []))
    column_ids = [column_id for column_id in rows[0].keys() if column_id not in excluded_columns] if rows else []
    columns = [{"name": key.replace("_", " ").title(), "id": key} for key in column_ids]
    numeric_columns = [
        column_id
        for column_id in column_ids
        if any(term in column_id.lower().split("_") for term in NUMERIC_COLUMN_TERMS)
    ]
    return dash_table.DataTable(
        id=table_id,
        data=rows,
        columns=columns,
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_table={
            "backgroundColor": "var(--color-surface)",
            "border": "1px solid var(--color-border)",
            "borderRadius": "var(--radius-md)",
            "overflowX": "auto",
        },
        style_cell={
            "backgroundColor": "var(--color-surface)",
            "border": "0",
            "borderBottom": "1px solid var(--color-border)",
            "color": "var(--color-text)",
            "fontFamily": "var(--font-family)",
            "fontSize": "0.8125rem",
            "padding": "0.625rem 0.75rem",
            "textAlign": "left",
        },
        style_cell_conditional=[
            {"if": {"column_id": column_id}, "fontVariantNumeric": "tabular-nums", "textAlign": "right"}
            for column_id in numeric_columns
        ],
        style_header={
            "backgroundColor": "var(--color-surface-elevated)",
            "borderBottom": "1px solid var(--color-border-strong)",
            "color": "var(--color-text)",
            "fontWeight": "700",
        },
        style_filter={
            "backgroundColor": "var(--color-surface)",
            "color": "var(--color-text)",
        },
        style_data_conditional=table_data_styles(),
        **kwargs,
    )
