from decimal import Decimal

from app.data.repositories import SeedRepository


def test_notaria_38_revenue_starts_with_the_august_ad_hoc_pilot() -> None:
    repo = SeedRepository()

    assert [client.id for client in repo.active_clients("2026-07")] == [1]
    assert repo.monthly_summary("2026-07")["revenue"] == Decimal("0")
    assert repo.monthly_summary("2026-08")["revenue"] == Decimal("5000")
    notaria_revenue = [event for event in repo.revenue_events() if event.client_id == 1]
    assert [(event.event_timestamp.date().isoformat(), event.amount) for event in notaria_revenue] == [
        ("2026-08-28", Decimal("5000"))
    ]


def test_inactive_client_usage_is_excluded_from_revenue_and_costs() -> None:
    repo = SeedRepository()
    summary = repo.monthly_summary("2026-06")

    assert repo.active_clients("2026-06") == []
    assert repo.usage_for_month("2026-06") == []
    assert summary["revenue"] == Decimal("0")
    assert summary["variable_cost"] == Decimal("0")
