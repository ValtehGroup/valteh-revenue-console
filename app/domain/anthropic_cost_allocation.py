from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.integrations.anthropic_admin_api import AnthropicCostRow, MessagesUsageRow


@dataclass(frozen=True)
class APIKeyUsageCostRow:
    date: str
    api_key_id: str
    workspace_id: str
    model: str
    service_tier: str
    uncached_input_tokens: int
    cache_creation_1h_tokens: int
    cache_creation_5m_tokens: int
    cache_read_tokens: int
    output_tokens: int
    web_search_requests: int
    allocated_cost_usd: Decimal = Decimal("0")

    @classmethod
    def from_usage(cls, usage: MessagesUsageRow) -> APIKeyUsageCostRow:
        return cls(
            date=usage.date,
            api_key_id=usage.api_key_id,
            workspace_id=usage.workspace_id,
            model=usage.model,
            service_tier=usage.service_tier,
            uncached_input_tokens=usage.uncached_input_tokens,
            cache_creation_1h_tokens=usage.cache_creation_1h_tokens,
            cache_creation_5m_tokens=usage.cache_creation_5m_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            output_tokens=usage.output_tokens,
            web_search_requests=usage.web_search_requests,
        )

    @property
    def input_tokens(self) -> int:
        return (
            self.uncached_input_tokens
            + self.cache_creation_1h_tokens
            + self.cache_creation_5m_tokens
            + self.cache_read_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CostAllocationResult:
    rows: tuple[APIKeyUsageCostRow, ...]
    allocated_cost_usd: Decimal
    unallocated_cost_usd: Decimal


def allocate_anthropic_costs(
    usage_rows: tuple[MessagesUsageRow, ...] | list[MessagesUsageRow],
    cost_rows: tuple[AnthropicCostRow, ...] | list[AnthropicCostRow],
) -> CostAllocationResult:
    """Allocate billed cost lines to API-key usage using matching billed units.

    Anthropic does not expose cost grouped by API key. Each daily cost line is
    therefore matched by date, workspace, model, and token/tool type, then
    distributed in proportion to the corresponding usage units. Unmatched
    costs remain explicit instead of being silently assigned.
    """

    allocations = [APIKeyUsageCostRow.from_usage(row) for row in usage_rows]
    allocated_total = Decimal("0")
    unallocated_total = Decimal("0")

    for cost in cost_rows:
        candidates = [
            (index, row)
            for index, row in enumerate(allocations)
            if row.date == cost.date
            and row.workspace_id == cost.workspace_id
            and (cost.model == "Not specified" or row.model == cost.model)
        ]
        units = [(index, _allocation_units(row, cost)) for index, row in candidates]
        units = [(index, quantity) for index, quantity in units if quantity > 0]
        total_units = sum((quantity for _, quantity in units), Decimal("0"))
        if total_units == 0:
            unallocated_total += cost.amount_usd
            continue

        for index, quantity in units:
            share = cost.amount_usd * quantity / total_units
            allocations[index] = replace(
                allocations[index],
                allocated_cost_usd=allocations[index].allocated_cost_usd + share,
            )
            allocated_total += share

    return CostAllocationResult(
        rows=tuple(allocations),
        allocated_cost_usd=allocated_total,
        unallocated_cost_usd=unallocated_total,
    )


def _allocation_units(row: APIKeyUsageCostRow, cost: AnthropicCostRow) -> Decimal:
    token_units = {
        "uncached_input_tokens": row.uncached_input_tokens,
        "output_tokens": row.output_tokens,
        "cache_read_input_tokens": row.cache_read_tokens,
        "cache_creation_1h_input_tokens": row.cache_creation_1h_tokens,
        "cache_creation_5m_input_tokens": row.cache_creation_5m_tokens,
        "cache_creation_input_tokens": row.cache_creation_1h_tokens + row.cache_creation_5m_tokens,
    }
    if cost.token_type in token_units:
        return Decimal(token_units[cost.token_type])
    if cost.cost_type == "web_search" or "Web Search" in cost.description:
        return Decimal(row.web_search_requests)
    if cost.cost_type == "tokens":
        return Decimal(row.total_tokens)
    return Decimal("0")
