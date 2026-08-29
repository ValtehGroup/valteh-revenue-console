import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, no_update

from app.domain.fx_rates import FxRateUnavailableError
from app.pages import (
    client_detail,
    clients,
    costs,
    executive_dashboard,
    pricing,
    scenarios,
    usage,
    user_guide,
)


def register_routes(app) -> None:
    executive_dashboard.register_callbacks(app)
    client_detail.register_callbacks(app)
    clients.register_callbacks(app)
    costs.register_callbacks(app)
    pricing.register_callbacks(app)
    scenarios.register_callbacks(app)
    usage.register_callbacks(app)

    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
        Input("theme-store", "data"),
        Input("display-currency-store", "data"),
        State("page-content", "children"),
    )
    def render_page(
        pathname: str,
        _theme_state: dict | None,
        display_currency: str | None,
        current_page: object | None,
    ):
        if _preserve_page_on_shell_change(pathname, ctx.triggered_id, current_page is not None):
            return no_update
        try:
            return page_layout(pathname, display_currency)
        except FxRateUnavailableError as exc:
            return dbc.Alert(str(exc), color="danger")


def _preserve_page_on_theme_change(pathname: str, triggered_id: str | None, page_is_mounted: bool) -> bool:
    return _preserve_page_on_shell_change(pathname, triggered_id, page_is_mounted)


def _preserve_page_on_shell_change(pathname: str, triggered_id: str | None, page_is_mounted: bool) -> bool:
    return pathname == "/usage" and triggered_id in {"theme-store", "display-currency-store"} and page_is_mounted


def page_layout(pathname: str, display_currency: str | None = "MXN"):
    if pathname == "/clients":
        return clients.layout(display_currency)
    if pathname == "/client-detail":
        return clients.layout(display_currency)
    if pathname == "/costs":
        return costs.layout(display_currency)
    if pathname == "/pricing":
        return pricing.layout(display_currency)
    if pathname == "/usage":
        return usage.layout()
    if pathname == "/scenarios":
        return scenarios.layout(display_currency)
    if pathname == "/guide":
        return user_guide.layout()
    return executive_dashboard.layout(display_currency)
