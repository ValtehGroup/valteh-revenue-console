import calendar
from datetime import date
from decimal import Decimal

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Input, Output, State, dcc, html

from app.components.charts import bar_chart
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.utils.currency import format_mxn


def layout():
    repo = SeedRepository()
    available_months = repo.available_months()
    selected_month = _default_month(available_months)
    selected_year = selected_month[:4]
    return html.Div(
        [
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
                    dbc.Alert(
                        [
                            html.Strong("To change a price without losing history: "),
                            "set the old row's end_date, then add a new row with the same cost_key and the new "
                            "start_date. Keep actual, budget, and estimate records separate with record_type.",
                        ],
                        color="info",
                    ),
                    dbc.Card(
                        dbc.CardBody(data_table("costs-table", _catalog_rows(repo), 15)),
                        className="border-0 shadow-sm",
                    ),
                ]
            ),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("costs-month-filter", "options"),
        Output("costs-month-filter", "value"),
        Input("costs-year-filter", "value"),
        State("costs-month-filter", "value"),
    )
    def update_month_options(year: str, selected_month: str | None):
        available_months = SeedRepository().available_months()
        months = _months_for_year(available_months, year)
        if selected_month not in months:
            selected_month = months[-1]
        return _month_options(available_months, year), selected_month

    @app.callback(
        Output("costs-dashboard-content", "children"),
        Input("costs-month-filter", "value"),
    )
    def update_dashboard(selected_month: str | None):
        available_months = SeedRepository().available_months()
        return _dashboard_content(
            selected_month if selected_month in available_months else _default_month(available_months)
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
                className="border-0 shadow-sm mb-4",
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
                className="border-0 shadow-sm mb-4",
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


def _catalog_rows(repo: SeedRepository) -> list[dict]:
    return [
        {
            "cost_key": item.cost_key,
            "name": item.name,
            "provider": item.provider or "",
            "category": item.category,
            "service_line": item.service_line or "Shared",
            "cost_type": item.cost_type,
            "record_type": item.record_type,
            "quantity": f"{item.quantity:f}",
            "unit_cost": f"{float(item.unit_cost):,.4f}",
            "configured_amount": format_mxn(item.configured_amount),
            "unit": item.unit,
            "frequency": item.billing_frequency,
            "start_date": item.start_date.isoformat() if item.start_date else "",
            "end_date": item.end_date.isoformat() if item.end_date else "",
            "enabled": item.enabled,
            "notes": item.notes or "",
        }
        for item in repo.cost_items()
    ]


def _monthly_cost_rows(repo: SeedRepository, selected_month: str) -> list[dict]:
    return [
        {
            "cost_key": cost.cost_key,
            "name": cost.name,
            "provider": cost.provider or "",
            "category": cost.category,
            "service_line": cost.service_line,
            "cost_type": cost.cost_type,
            "quantity": f"{cost.quantity:f}",
            "unit_cost": f"{float(cost.unit_cost):,.4f}",
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
            className="shadow-sm border-0 h-100",
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
        html.Div(title, className="text-muted small text-uppercase"),
        html.Div(format_mxn(split["total"]), className="h3 mb-1 text-primary"),
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
                html.Div("Click to hide split", className="small text-muted mt-1"),
            ]
        )
    else:
        content.append(html.Div("Click for fixed / variable split", className="small text-muted"))
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
        labels={"amount": "Cost (MXN)", "month": "", "cost_type": "Cost type"},
        color_discrete_map={"Fixed + one-time": "#2563eb", "Variable": "#f59e0b"},
    )
    figure.update_layout(
        legend_title_text="",
        margin=dict(l=20, r=20, t=50, b=20),
        hovermode="closest",
    )
    figure.update_traces(hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>$%{y:,.2f} MXN<extra></extra>")
    figure.update_xaxes(type="category", tickformat="%Y-%m")
    figure.update_yaxes(tickprefix="$", separatethousands=True)
    return figure
