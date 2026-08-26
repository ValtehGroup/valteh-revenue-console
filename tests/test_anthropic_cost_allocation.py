from decimal import Decimal

from app.domain.anthropic_cost_allocation import allocate_anthropic_costs
from app.integrations.anthropic_admin_api import AnthropicCostRow, MessagesUsageRow


def _usage(api_key_id: str, uncached_input: int, output: int = 0) -> MessagesUsageRow:
    return MessagesUsageRow(
        date="2026-08-25",
        api_key_id=api_key_id,
        workspace_id="wrkspc_123",
        model="claude-sonnet",
        service_tier="standard",
        uncached_input_tokens=uncached_input,
        cache_creation_1h_tokens=0,
        cache_creation_5m_tokens=0,
        cache_read_tokens=0,
        output_tokens=output,
        web_search_requests=0,
    )


def _cost(token_type: str, amount: str, *, model: str = "claude-sonnet") -> AnthropicCostRow:
    return AnthropicCostRow(
        date="2026-08-25",
        workspace_id="wrkspc_123",
        description="Claude usage",
        model=model,
        cost_type="tokens",
        token_type=token_type,
        amount_usd=Decimal(amount),
    )


def test_cost_is_allocated_to_api_keys_by_the_matching_usage_unit() -> None:
    result = allocate_anthropic_costs(
        [_usage("apikey_dev", 75, 10), _usage("apikey_prod", 25, 30)],
        [_cost("uncached_input_tokens", "4.00"), _cost("output_tokens", "8.00")],
    )

    assert result.rows[0].allocated_cost_usd == Decimal("5.00")
    assert result.rows[1].allocated_cost_usd == Decimal("7.00")
    assert result.allocated_cost_usd == Decimal("12.00")
    assert result.unallocated_cost_usd == Decimal("0")


def test_unmatched_cost_remains_unallocated() -> None:
    result = allocate_anthropic_costs(
        [_usage("apikey_dev", 100)],
        [_cost("uncached_input_tokens", "2.50", model="claude-opus")],
    )

    assert result.rows[0].allocated_cost_usd == Decimal("0")
    assert result.allocated_cost_usd == Decimal("0")
    assert result.unallocated_cost_usd == Decimal("2.50")
