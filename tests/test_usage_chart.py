from app.pages.usage import _token_usage_figure


def test_token_usage_chart_orders_dates_across_api_key_series() -> None:
    rows = [
        {"date": "2026-08-03", "api_key_name": "production-api-key", "total_tokens": 50},
        {"date": "2026-08-07", "api_key_name": "production-api-key", "total_tokens": 75},
        {"date": "2026-08-05", "api_key_name": "dev-api-key", "total_tokens": 25},
    ]

    figure = _token_usage_figure(rows, "api_key")

    assert figure.layout.xaxis.categoryorder == "array"
    assert list(figure.layout.xaxis.categoryarray) == ["2026-08-03", "2026-08-05", "2026-08-07"]
