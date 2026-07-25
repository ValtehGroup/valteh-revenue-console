from decimal import Decimal

from app.data.repositories import SeedRepository


def test_seed_has_only_notaria_38_active_in_july() -> None:
    repo = SeedRepository()

    assert [client.id for client in repo.active_clients("2026-07")] == [1]
    assert repo.monthly_summary("2026-07")["revenue"] == Decimal("10000")


def test_inactive_client_usage_is_excluded_from_revenue_and_costs() -> None:
    repo = SeedRepository()
    summary = repo.monthly_summary("2026-06")

    assert repo.active_clients("2026-06") == []
    assert repo.usage_for_month("2026-06") == []
    assert summary["revenue"] == Decimal("0")
    assert summary["variable_cost"] == Decimal("0")
