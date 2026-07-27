import dash_bootstrap_components as dbc
from dash import dcc

from app.data.repositories import SeedRepository


def month_filter(component_id: str = "month-filter", value: str | None = None) -> dbc.Col:
    months = SeedRepository().available_months()
    selected_value = value if value in months else months[-1]
    return dbc.Col(
        [
            dbc.Label("Month"),
            dcc.Dropdown(
                id=component_id,
                options=[{"label": month, "value": month} for month in months],
                value=selected_value,
                clearable=False,
                persistence=True,
                persistence_type="session",
            ),
        ],
        md=3,
    )


def scenario_filter(component_id: str = "scenario-filter") -> dbc.Col:
    scenarios = ["Base case", "Conservative case", "Growth case", "Stress case"]
    return dbc.Col(
        [
            dbc.Label("Scenario"),
            dcc.Dropdown(
                id=component_id,
                options=[{"label": scenario, "value": scenario} for scenario in scenarios],
                value="Base case",
                clearable=False,
                persistence=True,
                persistence_type="session",
            ),
        ],
        md=3,
    )
