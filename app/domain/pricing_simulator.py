from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.domain.models import PricingPlan
from app.domain.unit_economics import calculate_break_even_clients, calculate_minimum_unit_price, money


@dataclass(frozen=True)
class PricingSimulationInput:
    pricing_plan: PricingPlan
    clients: int
    onboarding_clients: int
    documents_per_client: Decimal
    validations_per_client: Decimal
    graph_queries_per_client: Decimal
    blockchain_transactions_per_client: Decimal
    folios_per_client: Decimal
    fixed_costs: Decimal
    document_unit_cost: Decimal
    validation_unit_cost: Decimal
    graph_query_unit_cost: Decimal
    blockchain_transaction_unit_cost: Decimal
    folio_unit_cost: Decimal
    blockchain_server_hours: Decimal = Decimal("0")
    blockchain_server_cost_per_hour: Decimal = Decimal("0")
    price_multiplier: Decimal = Decimal("1")
    variable_cost_multiplier: Decimal = Decimal("1")
    target_unit_margin: Decimal = Decimal("0.60")


@dataclass(frozen=True)
class PricingSimulationResult:
    revenue: Decimal
    subscription_revenue: Decimal
    setup_revenue: Decimal
    usage_revenue: Decimal
    variable_cost: Decimal
    fixed_cost: Decimal
    total_cost: Decimal
    operating_margin: Decimal
    operating_margin_percentage: Decimal
    revenue_per_client: Decimal
    variable_cost_per_client: Decimal
    break_even_clients: int | None
    minimum_document_price: Decimal
    recurring_revenue_per_document: Decimal | None


def simulate_pricing(input_data: PricingSimulationInput) -> PricingSimulationResult:
    clients = Decimal(input_data.clients)
    subscription_revenue = clients * money(input_data.pricing_plan.monthly_fixed_fee or 0)
    setup_revenue = Decimal(input_data.onboarding_clients) * money(input_data.pricing_plan.setup_fee or 0)
    usage_revenue_per_client = usage_revenue_for_client(input_data)
    usage_revenue = clients * usage_revenue_per_client
    variable_cost_per_client = variable_cost_for_client(input_data)
    variable_cost = clients * variable_cost_per_client
    fixed_cost = money(input_data.fixed_costs)
    revenue = subscription_revenue + setup_revenue + usage_revenue
    total_cost = variable_cost + fixed_cost
    operating_margin = revenue - total_cost
    operating_margin_percentage = operating_margin / revenue if revenue else Decimal("0")
    recurring_margin_per_client = (
        money(input_data.pricing_plan.monthly_fixed_fee or 0) + usage_revenue_per_client - variable_cost_per_client
    )
    break_even_clients = _safe_break_even_clients(fixed_cost, recurring_margin_per_client)
    minimum_document_price = calculate_minimum_unit_price(
        money(input_data.document_unit_cost) * money(input_data.variable_cost_multiplier),
        money(input_data.target_unit_margin),
    )
    recurring_revenue_per_document = (
        (subscription_revenue + usage_revenue) / (clients * money(input_data.documents_per_client))
        if clients and money(input_data.documents_per_client) > 0
        else None
    )
    return PricingSimulationResult(
        revenue=revenue,
        subscription_revenue=subscription_revenue,
        setup_revenue=setup_revenue,
        usage_revenue=usage_revenue,
        variable_cost=variable_cost,
        fixed_cost=fixed_cost,
        total_cost=total_cost,
        operating_margin=operating_margin,
        operating_margin_percentage=operating_margin_percentage,
        revenue_per_client=revenue / clients if clients else Decimal("0"),
        variable_cost_per_client=variable_cost_per_client,
        break_even_clients=break_even_clients,
        minimum_document_price=minimum_document_price,
        recurring_revenue_per_document=recurring_revenue_per_document,
    )


def crossover_documents(current_plan: PricingPlan, next_plan: PricingPlan, *, maximum: int = 100_000) -> int | None:
    """Return the first whole-document volume where the next plan is no more expensive."""

    for documents in range(max((current_plan.included_documents or 0) + 1, 1), maximum + 1):
        if _recurring_plan_revenue(next_plan, documents) <= _recurring_plan_revenue(current_plan, documents):
            return documents
    return None


def _recurring_plan_revenue(plan: PricingPlan, documents: int) -> Decimal:
    return money(plan.monthly_fixed_fee or 0) + billable_units(
        Decimal(documents), plan.included_documents or 0
    ) * money(plan.price_per_document or 0)


def usage_revenue_for_client(input_data: PricingSimulationInput) -> Decimal:
    plan = input_data.pricing_plan
    price_multiplier = money(input_data.price_multiplier)
    return (
        billable_units(input_data.documents_per_client, plan.included_documents or 0)
        * money(plan.price_per_document or 0)
        * price_multiplier
        + billable_units(input_data.validations_per_client, plan.included_validations)
        * money(plan.price_per_validation)
        * price_multiplier
        + billable_units(input_data.graph_queries_per_client, plan.included_graph_queries)
        * money(plan.price_per_graph_query)
        * price_multiplier
        + billable_units(input_data.blockchain_transactions_per_client, plan.included_blockchain_transactions)
        * money(plan.price_per_blockchain_transaction)
        * price_multiplier
        + money(input_data.folios_per_client) * money(plan.price_per_property_mint) * price_multiplier
    )


def variable_cost_for_client(input_data: PricingSimulationInput) -> Decimal:
    multiplier = money(input_data.variable_cost_multiplier)
    return (
        money(input_data.documents_per_client) * money(input_data.document_unit_cost)
        + money(input_data.validations_per_client) * money(input_data.validation_unit_cost)
        + money(input_data.graph_queries_per_client) * money(input_data.graph_query_unit_cost)
        + money(input_data.blockchain_transactions_per_client) * money(input_data.blockchain_transaction_unit_cost)
        + money(input_data.folios_per_client) * money(input_data.folio_unit_cost)
        + money(input_data.blockchain_server_hours) * money(input_data.blockchain_server_cost_per_hour)
    ) * multiplier


def billable_units(usage: Decimal, included: int) -> Decimal:
    return max(money(usage) - Decimal(included), Decimal("0"))


def sensitivity_series(
    base_input: PricingSimulationInput,
    usage_multipliers: list[Decimal],
    price_multipliers: list[Decimal],
) -> list[dict]:
    rows = []
    for price_multiplier in price_multipliers:
        for usage_multiplier in usage_multipliers:
            scenario_input = apply_usage_multiplier(
                base_input,
                usage_multiplier=usage_multiplier,
                price_multiplier=price_multiplier,
            )
            result = simulate_pricing(scenario_input)
            rows.append(
                {
                    "price_case": f"{price_multiplier:.0%} price",
                    "usage_multiplier": float(usage_multiplier),
                    "revenue": result.revenue,
                    "total_cost": result.total_cost,
                    "operating_margin": result.operating_margin,
                }
            )
    return rows


def apply_usage_multiplier(
    input_data: PricingSimulationInput,
    usage_multiplier: Decimal,
    price_multiplier: Decimal | None = None,
) -> PricingSimulationInput:
    multiplier = money(usage_multiplier)
    return PricingSimulationInput(
        pricing_plan=input_data.pricing_plan,
        clients=input_data.clients,
        onboarding_clients=input_data.onboarding_clients,
        documents_per_client=money(input_data.documents_per_client) * multiplier,
        validations_per_client=money(input_data.validations_per_client) * multiplier,
        graph_queries_per_client=money(input_data.graph_queries_per_client) * multiplier,
        blockchain_transactions_per_client=money(input_data.blockchain_transactions_per_client) * multiplier,
        folios_per_client=money(input_data.folios_per_client) * multiplier,
        fixed_costs=input_data.fixed_costs,
        document_unit_cost=input_data.document_unit_cost,
        validation_unit_cost=input_data.validation_unit_cost,
        graph_query_unit_cost=input_data.graph_query_unit_cost,
        blockchain_transaction_unit_cost=input_data.blockchain_transaction_unit_cost,
        folio_unit_cost=input_data.folio_unit_cost,
        blockchain_server_hours=input_data.blockchain_server_hours,
        blockchain_server_cost_per_hour=input_data.blockchain_server_cost_per_hour,
        price_multiplier=price_multiplier if price_multiplier is not None else input_data.price_multiplier,
        variable_cost_multiplier=input_data.variable_cost_multiplier,
        target_unit_margin=input_data.target_unit_margin,
    )


def cost_sensitivity_series(
    base_input: PricingSimulationInput,
    cost_variable: str,
    multipliers: list[Decimal],
) -> list[dict]:
    """Vary one cost variable and return operating margin results."""

    base_value = money(getattr(base_input, cost_variable))
    rows = []
    for multiplier in multipliers:
        tested_value = base_value * money(multiplier)
        scenario_input = replace(base_input, **{cost_variable: tested_value})
        result = simulate_pricing(scenario_input)
        rows.append(
            {
                "cost_variable": cost_variable,
                "cost_value": tested_value,
                "multiplier": multiplier,
                "revenue": result.revenue,
                "total_cost": result.total_cost,
                "operating_margin": result.operating_margin,
            }
        )
    return rows


def _safe_break_even_clients(fixed_cost: Decimal, recurring_margin_per_client: Decimal) -> int | None:
    if recurring_margin_per_client <= 0:
        return None
    return calculate_break_even_clients(fixed_cost, recurring_margin_per_client)
