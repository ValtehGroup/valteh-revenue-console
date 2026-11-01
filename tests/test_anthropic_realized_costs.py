from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.components.anthropic_costs import anthropic_cost_breakdown
from app.data.anthropic_assignment_repository import AnthropicAssignmentRepository
from app.data.anthropic_history_repository import AnthropicHistoryRepository
from app.data.repositories import SeedRepository
from app.domain.anthropic_cost_allocation import allocate_anthropic_costs
from app.domain.anthropic_realized_costs import realized_anthropic_costs, replace_catalog_costs
from app.domain.cost_engine import monthly_cost_amounts
from app.domain.display_currency import translate_cost_amount
from app.domain.fx_rates import USD_MXN_FIX_SERIES_ID, DatedFxRateBook, FxRateObservation, FxRateUnavailableError
from app.domain.models import CostItem, UsageEvent
from app.integrations.anthropic_admin_api import (
    AnthropicAdminReport,
    AnthropicAPIKeyMetadata,
    AnthropicCostRow,
    MessagesUsageRow,
)

DAY = date(2026, 10, 1)


def _report():
    keys = ("production-api-key", "dev-api-key", "sandbox-api-key")
    return AnthropicAdminReport(
        usage_rows=(),
        messages_usage_rows=tuple(
            MessagesUsageRow(str(DAY), f"apikey_{i}", "workspace", "claude", "standard", 1, 0, 0, 0, 0, 0)
            for i in range(3)
        ),
        cost_rows=(
            AnthropicCostRow(
                str(DAY), "workspace", "Tokens", "claude", "tokens", "uncached_input_tokens", Decimal("3")
            ),
        ),
        api_keys=tuple(
            AnthropicAPIKeyMetadata(f"apikey_{i}", name, "active", "workspace", "") for i, name in enumerate(keys)
        ),
    )


def _rates():
    return DatedFxRateBook([FxRateObservation(USD_MXN_FIX_SERIES_ID, DAY, Decimal("20"))], maximum_age_days=None)


def _period(key="apikey_0", client_id=1, start=DAY, end=None):
    return SimpleNamespace(
        api_key_id=key, environment="production", client_id=client_id, effective_from=start, effective_to=end
    )


def test_internal_costs_never_reach_clients_and_production_stays_pending():
    amounts = realized_anthropic_costs(_report(), [_period("apikey_1"), _period("apikey_2")], _rates())
    assert sum(a.amount for a in amounts) == Decimal("60")
    assert sum(a.amount for a in amounts if a.cost_scope == "internal") == Decimal("40")
    assert sum(a.amount for a in amounts if a.cost_scope == "production_unassigned") == Decimal("20")
    assert all(a.client_id is None for a in amounts)
    assert sum(translate_cost_amount(a, "USD", {}) for a in amounts) == Decimal("3")


def test_manual_production_assignment_respects_inclusive_effective_dates():
    periods = [_period(client_id=1, end=DAY), _period(client_id=2, start=date(2026, 10, 2))]
    amounts = realized_anthropic_costs(_report(), periods, _rates())
    assert [(a.client_id, a.amount) for a in amounts if a.cost_scope == "client"] == [(1, Decimal("20"))]
    amounts = realized_anthropic_costs(_report(), [_period(start=date(2026, 10, 2))], _rates())
    assert not any(a.client_id for a in amounts)


def test_unmatched_billed_cost_is_in_company_total_and_unknown_keys_stay_unassigned():
    report = _report()
    report = replace(
        report,
        api_keys=(),
        cost_rows=report.cost_rows + (replace(report.cost_rows[0], model="other", amount_usd=Decimal("2")),),
    )
    amounts = realized_anthropic_costs(report, [], _rates())
    assert sum(a.amount for a in amounts) == Decimal("100")
    assert all(a.cost_scope == "unassigned" for a in amounts)


def test_missing_fx_fails_explicitly():
    with pytest.raises(FxRateUnavailableError):
        realized_anthropic_costs(_report(), [], DatedFxRateBook([]))


def test_allocations_reconcile_even_for_repeating_decimal_shares():
    report = _report()
    result = allocate_anthropic_costs(
        report.messages_usage_rows, [replace(report.cost_rows[0], amount_usd=Decimal("1"))]
    )
    assert sum(row.allocated_cost_usd for row in result.rows) == Decimal("1")


def _catalog():
    return [
        CostItem(
            id=i,
            cost_key=key,
            name=key,
            provider=provider,
            category="AI",
            service_line="SAREMI",
            cost_type="variable",
            charge_basis="usage",
            unit_cost=Decimal("2"),
            unit="saremi.document_validation",
            billing_frequency="usage",
            start_date=DAY,
        )
        for i, key, provider in [(1, "ai.claude.document_analysis", "Anthropic"), (2, "local.preprocessing", "SAREMI")]
    ]


def _usage():
    return [
        UsageEvent(
            id=1,
            client_id=1,
            service_code="saremi",
            event_type="saremi.document_validation",
            quantity=Decimal("1"),
            unit="document",
            event_timestamp=datetime(2026, 10, 1),
            source_system="test",
        )
    ]


def test_replace_only_overlapping_claude_cost_not_separate_saremi_work():
    items = _catalog()
    amounts = monthly_cost_amounts(items, DAY, _usage())
    assert sum(a.amount for a in replace_catalog_costs(amounts, items, {DAY})) == Decimal("2")
    assert sum(a.amount for a in replace_catalog_costs(amounts, items, {date(2026, 10, 2)})) == Decimal("4")


def test_token_allowances_never_duplicate_bills_but_base_subscription_remains():
    template = _catalog()[0]
    items = [
        template.model_copy(
            update={
                "id": i,
                "cost_key": str(i),
                "name": name,
                "cost_type": "fixed",
                "billing_frequency": "monthly",
                "unit": "month",
            }
        )
        for i, name in enumerate(["Claude Tokens Prod", "Claude Tokens Dev", "Claude Anthropic Subscription"], 10)
    ]
    amounts = monthly_cost_amounts(items, DAY)
    for coverage in [set(), {date(2026, 10, 31)}]:
        retained = replace_catalog_costs(amounts, items, coverage)
        assert [a.name for a in retained] == ["Claude Anthropic Subscription"]


def test_repository_totals_clients_history_and_breakdown_reconcile(monkeypatch):
    monkeypatch.setattr(AnthropicHistoryRepository, "load_report", lambda *args: _report())
    monkeypatch.setattr(AnthropicHistoryRepository, "cost_covered_dates", lambda *args: {DAY})
    monkeypatch.setattr(AnthropicAssignmentRepository, "list_assignment_periods", lambda *args: [_period()])
    monkeypatch.setattr(SeedRepository, "cost_items", lambda *args: _catalog())
    monkeypatch.setattr(SeedRepository, "usage_for_month", lambda *args: _usage())
    monkeypatch.setattr(SeedRepository, "usage_history_for_client_month", lambda *args: _usage())
    monkeypatch.setattr(SeedRepository, "monthly_revenue_amounts", lambda *args, **kwargs: [])
    monkeypatch.setattr(SeedRepository, "clients", lambda *args: [])
    monkeypatch.setattr(SeedRepository, "active_clients", lambda *args: [])
    monkeypatch.setattr(SeedRepository, "available_months", lambda *args: ["2026-10"])
    monkeypatch.setattr(SeedRepository, "_fx_rate_book", lambda *args: _rates())
    repo = SeedRepository()
    presentation = repo.monthly_presentation("2026-10")
    assert presentation["summary"]["variable_cost"] == Decimal("62")
    assert repo.monthly_summary("2026-10")["variable_cost"] == Decimal("62")
    assert repo.cost_history()[0]["variable"] == Decimal("62")
    assert repo.client_monthly_presentation(1, "2026-10")["variable_cost"] == Decimal("22")
    content = str(anthropic_cost_breakdown(presentation, [], "test"))
    assert "Internal development / testing" in content
    assert "Assigned production" in content


def test_synced_zero_replaces_catalog_without_needing_fx(monkeypatch):
    monkeypatch.setattr(AnthropicHistoryRepository, "load_report", lambda *args: AnthropicAdminReport((), (), ()))
    monkeypatch.setattr(AnthropicHistoryRepository, "cost_covered_dates", lambda *args: {DAY})
    amounts = monthly_cost_amounts(_catalog(), DAY, _usage())
    result = SeedRepository()._reconcile_anthropic_costs("2026-10", amounts, _catalog())
    assert sum(a.amount for a in result) == Decimal("2")
