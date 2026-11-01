from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.anthropic_cost_allocation import allocate_anthropic_costs
from app.domain.cost_engine import CostAmount, FxRateResolver
from app.domain.models import CostItem
from app.integrations.anthropic_admin_api import AnthropicAdminReport


class KeyAssignmentPeriod(Protocol):
    api_key_id: str
    environment: str
    client_id: int
    effective_from: date
    effective_to: date | None


def key_environment(name: str) -> str:
    normalized = name.strip().lower()
    if normalized == "production-api-key":
        return "production"
    if normalized in {"dev-api-key", "sandbox-api-key"}:
        return "internal"
    return "unassigned"


def is_anthropic_catalog_cost(item: CostItem) -> bool:
    """Only replace Claude inference; local SAREMI work is a separate cost."""
    return item.cost_type == "variable" and (
        (item.provider or "").strip().lower() == "anthropic" or item.cost_key == "ai.claude.document_analysis"
    )


def is_anthropic_token_allowance(item: CostItem) -> bool:
    """Catalog token allowances are consumption placeholders, not fixed subscriptions."""
    return (item.provider or "").strip().lower() == "anthropic" and item.name.strip().lower() in {
        "claude tokens prod",
        "claude tokens dev",
    }


def replace_catalog_costs(
    amounts: Sequence[CostAmount], items: Sequence[CostItem], covered_dates: set[date]
) -> list[CostAmount]:
    replaced_keys = {item.cost_key for item in items if is_anthropic_catalog_cost(item)}
    allowance_keys = {item.cost_key for item in items if is_anthropic_token_allowance(item)}
    return [
        amount
        for amount in amounts
        if amount.cost_key not in allowance_keys
        and not (amount.cost_key in replaced_keys and amount.valuation_date in covered_dates)
    ]


def realized_anthropic_costs(
    report: AnthropicAdminReport,
    assignments: Sequence[KeyAssignmentPeriod],
    fx_rates: FxRateResolver,
) -> list[CostAmount]:
    """Preserve billed daily totals; API-key and client shares are derived allocations."""
    names = {key.id: key.name for key in report.api_keys}
    by_day: dict[str, list] = defaultdict(list)
    for cost in report.cost_rows:
        by_day[cost.date].append(cost)
    amounts = []
    for day, costs in sorted(by_day.items()):
        allocation = allocate_anthropic_costs([row for row in report.messages_usage_rows if row.date == day], costs)
        buckets: dict[tuple[str, str, int | None], Decimal] = defaultdict(lambda: Decimal("0"))
        valuation_date = date.fromisoformat(day)
        for row in allocation.rows:
            name = names.get(row.api_key_id, "Unknown API key")
            period = next(
                (
                    period
                    for period in assignments
                    if period.api_key_id == row.api_key_id
                    and period.effective_from <= valuation_date
                    and (period.effective_to is None or valuation_date <= period.effective_to)
                ),
                None,
            )
            environment = key_environment(name)
            if environment == "unassigned" and period is not None:
                environment = "production" if period.environment == "production" else "internal"
            client_id = period.client_id if period and environment == "production" else None
            scope = (
                "client"
                if client_id is not None
                else (
                    "production_unassigned"
                    if environment == "production"
                    else "internal" if environment == "internal" else "unassigned"
                )
            )
            buckets[(name, scope, client_id)] += row.allocated_cost_usd
        buckets[("Unallocated billed cost", "unassigned", None)] += allocation.unallocated_cost_usd
        rate = fx_rates.resolve("USD", valuation_date)
        for (name, scope, client_id), usd in buckets.items():
            if usd == 0:
                continue
            amounts.append(
                CostAmount(
                    cost_key="anthropic.billed",
                    name=name,
                    provider="Anthropic",
                    category="AI inference",
                    service_line=(
                        "SAREMI"
                        if scope in {"client", "production_unassigned"}
                        else "Valteh internal" if scope == "internal" else "Unassigned"
                    ),
                    cost_type="variable",
                    charge_basis="usage",
                    quantity=Decimal("1"),
                    unit_cost=usd * rate.rate,
                    currency="MXN",
                    unit="billed day",
                    billing_frequency="usage",
                    start_date=valuation_date,
                    end_date=valuation_date,
                    record_type="actual",
                    amount=usd * rate.rate,
                    source_unit_cost=usd,
                    source_currency="USD",
                    fx_rate=rate.rate,
                    valuation_date=valuation_date,
                    fx_rate_date=rate.observation_date,
                    client_id=client_id,
                    cost_scope=scope,
                )
            )
    return amounts
