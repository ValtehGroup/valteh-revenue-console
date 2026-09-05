from __future__ import annotations

from collections.abc import Callable
from datetime import date
from threading import Lock

from app.config import get_settings
from app.data.fx_rate_repository import FxRateRepository
from app.domain.fx_history_sync import FxHistorySyncResult, FxHistorySyncService, FxRateClient
from app.integrations.banxico_sie_api import BanxicoSIEClient

_refresh_lock = Lock()


def refresh_stale_fx_history(
    *,
    repository: FxRateRepository | None = None,
    client: FxRateClient | None = None,
    mexico_today: Callable[[], date] | None = None,
) -> FxHistorySyncResult | None:
    """Refresh persisted Banxico FIX history when it is older than the accepted age."""

    if client is None:
        token = get_settings().banxico_sie_token
        if token is None:
            return None
        client = BanxicoSIEClient(token.get_secret_value())

    with _refresh_lock:
        return FxHistorySyncService(
            client,
            repository or FxRateRepository(),
            mexico_today=mexico_today,
        ).sync_if_stale()
