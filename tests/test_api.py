import pytest

from app.config import get_settings
from app.main import app as dash_app


@pytest.fixture
def client():
    dash_app.server.config.update(TESTING=True)
    return dash_app.server.test_client()


def test_health(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_months_returns_seeded_range(client) -> None:
    response = client.get("/api/v1/months")

    assert response.status_code == 200
    assert "2026-07" in response.get_json()["months"]


def test_summary_defaults_to_current_month_and_rejects_bad_format(client) -> None:
    ok = client.get("/api/v1/summary?month=2026-07")
    bad = client.get("/api/v1/summary?month=not-a-month")

    assert ok.status_code == 200
    body = ok.get_json()
    assert body["month"] == "2026-07"
    assert {"revenue", "variable_cost", "fixed_cost", "gross_margin", "operating_margin", "burn_rate"} <= body.keys()
    assert isinstance(body["revenue"], float)

    assert bad.status_code == 400
    assert "month" in bad.get_json()["error"]


def test_revenue_and_cost_breakdowns(client) -> None:
    revenue = client.get("/api/v1/revenue/by-service?month=2026-07")
    split = client.get("/api/v1/revenue/split?month=2026-07")
    by_provider = client.get("/api/v1/costs/by-provider?month=2026-07")
    history = client.get("/api/v1/costs/history")

    assert revenue.status_code == 200
    assert "by_service" in revenue.get_json()
    assert split.status_code == 200
    assert {"subscription", "usage", "total"} <= split.get_json().keys()
    assert by_provider.status_code == 200
    assert history.status_code == 200
    assert isinstance(history.get_json()["history"], list)


def test_clients_listing_and_detail(client) -> None:
    listing = client.get("/api/v1/clients")
    detail = client.get("/api/v1/clients/1")
    missing = client.get("/api/v1/clients/9999")
    invalid_id = client.get("/api/v1/clients/not-an-id")

    assert listing.status_code == 200
    assert any(row["id"] == 1 for row in listing.get_json()["clients"])

    assert detail.status_code == 200
    assert detail.get_json()["id"] == 1

    assert missing.status_code == 404
    assert invalid_id.status_code == 400


def test_client_profitability_and_revenue_split(client) -> None:
    profitability = client.get("/api/v1/clients/1/profitability?month=2026-07")
    revenue_split = client.get("/api/v1/clients/1/revenue-split?month=2026-07")
    missing_client = client.get("/api/v1/clients/9999/profitability?month=2026-07")

    assert profitability.status_code == 200
    body = profitability.get_json()
    assert body["client_id"] == 1
    assert {"revenue", "variable_cost", "gross_margin", "gross_margin_percentage"} <= body.keys()

    assert revenue_split.status_code == 200
    assert {"subscription", "usage", "total"} <= revenue_split.get_json().keys()

    assert missing_client.status_code == 404


def test_usage_listing_supports_month_and_client_filters(client) -> None:
    unfiltered = client.get("/api/v1/usage")
    june = client.get("/api/v1/usage?month=2026-06")
    july = client.get("/api/v1/usage?month=2026-07")
    for_client_2 = client.get("/api/v1/usage?client_id=2")
    bad_month = client.get("/api/v1/usage?month=not-a-month")

    assert unfiltered.status_code == 200
    assert len(unfiltered.get_json()["usage"]) == 10

    assert june.status_code == 200
    assert len(june.get_json()["usage"]) == 10

    assert july.status_code == 200
    assert july.get_json()["usage"] == []

    assert for_client_2.status_code == 200
    rows = for_client_2.get_json()["usage"]
    assert len(rows) == 5
    assert all(row["client_id"] == 2 for row in rows)
    assert rows[0]["client_code"] == "test_0002"

    assert bad_month.status_code == 400


def test_client_usage_endpoint(client) -> None:
    with_usage = client.get("/api/v1/clients/2/usage?month=2026-06")
    without_usage = client.get("/api/v1/clients/1/usage?month=2026-07")
    missing_client = client.get("/api/v1/clients/9999/usage?month=2026-06")

    assert with_usage.status_code == 200
    body = with_usage.get_json()
    assert body["month"] == "2026-06"
    assert len(body["usage"]) == 5

    assert without_usage.status_code == 200
    assert without_usage.get_json()["usage"] == []

    assert missing_client.status_code == 404


def test_auth_required_when_token_configured(client, monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("REVENUE_API_TOKEN", "secret-token")
    get_settings.cache_clear()

    unauthorized = client.get("/api/v1/health")
    authorized = client.get("/api/v1/health", headers={"Authorization": "Bearer secret-token"})

    get_settings.cache_clear()
    monkeypatch.delenv("REVENUE_API_TOKEN", raising=False)
    get_settings.cache_clear()

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
