import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html

from app.domain.display_currency import DEFAULT_DISPLAY_CURRENCY, DISPLAY_CURRENCIES, normalize_display_currency


def display_currency_store() -> dcc.Store:
    return dcc.Store(
        id="display-currency-store",
        data=DEFAULT_DISPLAY_CURRENCY,
        storage_type="session",
    )


def display_currency_toggle() -> html.Div:
    return html.Div(
        [
            dbc.RadioItems(
                id="display-currency-toggle",
                options=[{"label": currency, "value": currency} for currency in DISPLAY_CURRENCIES],
                value=DEFAULT_DISPLAY_CURRENCY,
                inline=True,
                persistence=True,
                persistence_type="session",
                className="display-currency-options",
                inputClassName="btn-check",
                labelClassName="display-currency-option",
                labelCheckedClassName="active",
            ),
        ],
        className="display-currency-toggle",
        role="group",
        **{"aria-label": "Display currency"},
    )


def register_display_currency_callbacks(app) -> None:
    @app.callback(Output("display-currency-store", "data"), Input("display-currency-toggle", "value"))
    def persist_display_currency(value: str | None) -> str:
        return normalize_display_currency(value)
