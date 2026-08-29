import io
import json
from datetime import date
from decimal import Decimal

import pytest

from app.config import Settings
from app.integrations.banxico_sie_api import (
    BANXICO_USD_MXN_SERIES_ID,
    BanxicoSIEAPIError,
    BanxicoSIEClient,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: dict):
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _payload(*observations: tuple[str, str], series_id: str = BANXICO_USD_MXN_SERIES_ID) -> dict:
    return {
        "bmx": {
            "series": [
                {
                    "idSerie": series_id,
                    "titulo": "Tipo de cambio FIX",
                    "datos": [{"fecha": day, "dato": value} for day, value in observations],
                }
            ]
        }
    }


def test_client_requests_fix_range_with_header_without_exposing_token_in_url() -> None:
    requests = []

    def opener(request, _timeout):
        requests.append(request)
        return FakeResponse(_payload(("27/08/2026", "17.1234"), ("28/08/2026", "17.2000")))

    observations = BanxicoSIEClient("secret-token", opener=opener).fetch_usd_mxn_fix(
        date(2026, 8, 27), date(2026, 8, 28)
    )

    assert [(row.rate_date, row.rate) for row in observations] == [
        (date(2026, 8, 27), Decimal("17.1234")),
        (date(2026, 8, 28), Decimal("17.2000")),
    ]
    assert len(requests) == 1
    request = requests[0]
    assert f"/series/{BANXICO_USD_MXN_SERIES_ID}/datos/2026-08-27/2026-08-28" in request.full_url
    assert "secret-token" not in request.full_url
    assert request.get_header("Bmx-token") == "secret-token"


def test_client_ignores_not_available_observations() -> None:
    client = BanxicoSIEClient(
        "token",
        opener=lambda *_args: FakeResponse(_payload(("29/08/2026", "N/E"), ("28/08/2026", "17.25"))),
    )

    observations = client.fetch_usd_mxn_fix(date(2026, 8, 28), date(2026, 8, 29))

    assert len(observations) == 1
    assert observations[0].rate_date == date(2026, 8, 28)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_payload(("27/08/2026", "17"), series_id="WRONG"), "unexpected series"),
        (_payload(("invalid", "17")), "invalid observation date"),
        (_payload(("27/08/2026", "invalid")), "invalid exchange rate"),
        (_payload(("27/08/2026", "0")), "nonpositive"),
        (_payload(("26/08/2026", "17")), "outside the requested range"),
        (_payload(("27/08/2026", "17"), ("27/08/2026", "18")), "duplicate"),
    ],
)
def test_client_rejects_invalid_provider_observations(payload: dict, message: str) -> None:
    client = BanxicoSIEClient("token", opener=lambda *_args: FakeResponse(payload))

    with pytest.raises(BanxicoSIEAPIError, match=message):
        client.fetch_usd_mxn_fix(date(2026, 8, 27), date(2026, 8, 28))


def test_banxico_token_is_optional_and_redacted_by_settings() -> None:
    missing = Settings(_env_file=None, banxico_sie_token="")
    configured = Settings(_env_file=None, banxico_sie_token="secret-token")

    assert missing.banxico_sie_token is None
    assert configured.banxico_sie_token is not None
    assert configured.banxico_sie_token.get_secret_value() == "secret-token"
    assert "secret-token" not in repr(configured)
