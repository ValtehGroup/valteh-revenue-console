from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.domain.fx_rates import USD_MXN_FIX_SERIES_ID, FxRateObservation

BANXICO_API_BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1"
BANXICO_USD_MXN_SERIES_ID = USD_MXN_FIX_SERIES_ID


class BanxicoSIEAPIError(RuntimeError):
    """Safe, user-facing error raised when Banxico data cannot be loaded."""


def _open_url(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


class BanxicoSIEClient:
    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: float = 20,
        opener: Callable[[Request, float], Any] | None = None,
    ) -> None:
        token = token.strip()
        if not token:
            raise ValueError("Banxico SIE token is required.")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._opener = opener or _open_url

    def fetch_usd_mxn_fix(self, starting_at: date, ending_at: date) -> tuple[FxRateObservation, ...]:
        if ending_at < starting_at:
            raise ValueError("End date must be on or after start date.")
        url = (
            f"{BANXICO_API_BASE_URL}/series/{BANXICO_USD_MXN_SERIES_ID}/datos/"
            f"{starting_at.isoformat()}/{ending_at.isoformat()}"
        )
        request = Request(
            url,
            headers={"accept": "application/json", "Bmx-Token": self._token},
            method="GET",
        )
        try:
            with self._opener(request, self._timeout_seconds) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise BanxicoSIEAPIError(_http_error_message(exc.code)) from exc
        except (TimeoutError, URLError) as exc:
            raise BanxicoSIEAPIError("Could not connect to the Banxico SIE API.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise BanxicoSIEAPIError("Banxico returned an unreadable response.") from exc
        return _parse_fix_response(payload, starting_at, ending_at)


def _parse_fix_response(
    payload: Any,
    starting_at: date,
    ending_at: date,
) -> tuple[FxRateObservation, ...]:
    if not isinstance(payload, Mapping):
        raise BanxicoSIEAPIError("Banxico returned an invalid response.")
    bmx = payload.get("bmx")
    series = bmx.get("series") if isinstance(bmx, Mapping) else None
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)) or len(series) != 1:
        raise BanxicoSIEAPIError("Banxico returned an invalid series response.")
    item = series[0]
    if not isinstance(item, Mapping) or item.get("idSerie") != BANXICO_USD_MXN_SERIES_ID:
        raise BanxicoSIEAPIError("Banxico returned an unexpected series.")
    raw_observations = item.get("datos")
    if not isinstance(raw_observations, Sequence) or isinstance(raw_observations, (str, bytes)):
        raise BanxicoSIEAPIError("Banxico returned invalid series observations.")

    observations = []
    seen_dates = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise BanxicoSIEAPIError("Banxico returned an invalid observation.")
        raw_value = raw.get("dato")
        if isinstance(raw_value, str) and raw_value.strip().upper() == "N/E":
            continue
        observation = _parse_observation(raw, starting_at, ending_at)
        if observation.rate_date in seen_dates:
            raise BanxicoSIEAPIError("Banxico returned duplicate observation dates.")
        seen_dates.add(observation.rate_date)
        observations.append(observation)
    return tuple(sorted(observations, key=lambda observation: observation.rate_date))


def _parse_observation(raw: Mapping[str, Any], starting_at: date, ending_at: date) -> FxRateObservation:
    try:
        rate_date = datetime.strptime(str(raw.get("fecha", "")), "%d/%m/%Y").date()
    except ValueError as exc:
        raise BanxicoSIEAPIError("Banxico returned an invalid observation date.") from exc
    if not starting_at <= rate_date <= ending_at:
        raise BanxicoSIEAPIError("Banxico returned an observation outside the requested range.")
    try:
        rate = Decimal(str(raw.get("dato", "")).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise BanxicoSIEAPIError("Banxico returned an invalid exchange rate.") from exc
    if not rate.is_finite() or rate <= 0:
        raise BanxicoSIEAPIError("Banxico returned a nonpositive exchange rate.")
    return FxRateObservation(BANXICO_USD_MXN_SERIES_ID, rate_date, rate)


def _http_error_message(status_code: int) -> str:
    if status_code == 400:
        return "Banxico rejected the SIE request or token (HTTP 400)."
    if status_code in {401, 403}:
        return f"Banxico rejected the SIE token (HTTP {status_code})."
    if status_code == 429:
        return "Banxico rate-limited the SIE request (HTTP 429)."
    return f"Banxico SIE request failed (HTTP {status_code})."
