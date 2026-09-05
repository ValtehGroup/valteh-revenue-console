import logging
from collections.abc import Callable
from datetime import date, datetime

import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, html, no_update

from app.data.fx_rate_repository import FxRateRepository
from app.domain.fx_history_sync import MEXICO_CITY_TIMEZONE, fx_history_is_stale
from app.domain.fx_rates import FxRateUnavailableError
from app.integrations.automatic_fx_refresh import refresh_stale_fx_history
from app.integrations.banxico_sie_api import BanxicoSIEAPIError
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

logger = logging.getLogger(__name__)


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
        refresh_error = _refresh_fx_history_if_needed()
        try:
            page = page_layout(pathname, display_currency)
        except FxRateUnavailableError as exc:
            details = f" Automatic Banxico refresh failed: {refresh_error}" if refresh_error else ""
            return dbc.Alert(f"{exc}{details}", color="danger")
        warning = _stale_fx_warning()
        return html.Div([warning, page]) if warning is not None else page


def _refresh_fx_history_if_needed() -> str | None:
    try:
        refresh_stale_fx_history()
    except (BanxicoSIEAPIError, ValueError, RuntimeError) as exc:
        logger.warning("Automatic Banxico FIX refresh failed: %s", exc)
        return str(exc)
    except Exception:
        logger.exception("Automatic Banxico FIX refresh failed unexpectedly")
        return "FX history update failed."
    return None


def _stale_fx_warning(
    repository: FxRateRepository | None = None,
    mexico_today: Callable[[], date] | None = None,
):
    latest = (repository or FxRateRepository()).latest()
    today = (mexico_today or (lambda: datetime.now(MEXICO_CITY_TIMEZONE).date()))()
    if latest is None or not fx_history_is_stale(latest, today):
        return None
    return dbc.Alert(
        [
            html.Strong(f"Using the latest available Banxico FIX from {latest.rate_date.isoformat()}. "),
            html.Span("The exchange rate may not be current. Open Scenarios and select "),
            html.A("Update FX history", href="/scenarios", className="alert-link"),
            html.Span(" to try reloading Banxico data."),
        ],
        color="warning",
    )


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
