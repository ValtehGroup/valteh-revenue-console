from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.models import ClientSubscription, PricingPlan, UsageEvent
from app.domain.unit_economics import money


@dataclass(frozen=True)
class RevenueAmount:
    client_id: int
    service_line: str
    revenue_type: str
    amount_mxn: Decimal
    recognition_date: date
    source_amount: Decimal
    source_currency: str = "MXN"
    fx_rate: Decimal | None = None
    fx_rate_date: date | None = None
    provisional_fx: bool = False


EVENT_PRICE_FIELDS = {
    "saremi.document_validation": "price_per_document",
    "saremi.ine_validation": "price_per_validation",
    "graphos.query": "price_per_graph_query",
    "graphos.case_analysis": "price_per_graph_query",
    "blockchain.asiento_registration": "price_per_blockchain_transaction",
    "blockchain.certificate_issued": "price_per_blockchain_transaction",
    "blockchain.folio_mint": "price_per_property_mint",
}


def calculate_client_revenue(
    client_usage: Iterable[UsageEvent],
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
    period_month: date | None = None,
) -> Decimal:
    """Calculate fixed subscription revenue plus usage revenue for one client and period."""

    return calculate_subscription_revenue(pricing_plan, subscription, period_month) + calculate_usage_revenue(
        client_usage, pricing_plan
    )


def calculate_subscription_revenue(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
    period_month: date | None = None,
) -> Decimal:
    """Calculate setup, annual, and monthly fixed fees for one client and period."""

    revenue = money(pricing_plan.monthly_fixed_fee)
    if subscription and period_month:
        revenue += _setup_fee_for_month(pricing_plan, subscription, period_month)
        revenue += _annual_fee_for_month(pricing_plan, subscription, period_month)
    return revenue


def calculate_usage_revenue(client_usage: Iterable[UsageEvent], pricing_plan: PricingPlan) -> Decimal:
    """Calculate billable usage revenue after included quantities."""

    return sum(
        (amount.amount_mxn for amount in usage_revenue_amounts(client_usage, pricing_plan)),
        Decimal("0"),
    )


def revenue_amounts(
    client_usage: Iterable[UsageEvent],
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
    period_month: date | None = None,
    *,
    today: date | None = None,
) -> list[RevenueAmount]:
    amounts: list[RevenueAmount] = []
    if subscription is not None and period_month is not None:
        monthly_date, provisional = monthly_revenue_recognition_date(period_month, today=today)
        monthly_fee = money(pricing_plan.monthly_fixed_fee)
        if monthly_fee:
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    "SIGEN",
                    "monthly_subscription",
                    monthly_fee,
                    monthly_date,
                    monthly_fee,
                    provisional_fx=provisional,
                )
            )
        setup_fee = money(pricing_plan.setup_fee)
        if (
            setup_fee
            and subscription.start_date.year == period_month.year
            and subscription.start_date.month == period_month.month
        ):
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    "SIGEN",
                    "setup",
                    setup_fee,
                    subscription.start_date,
                    setup_fee,
                )
            )
        annual_fee = money(pricing_plan.annual_fee)
        if (
            annual_fee
            and period_month >= subscription.start_date
            and subscription.start_date.month == period_month.month
        ):
            anniversary = date(
                period_month.year,
                period_month.month,
                min(subscription.start_date.day, calendar.monthrange(period_month.year, period_month.month)[1]),
            )
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    "SIGEN",
                    "annual",
                    annual_fee,
                    anniversary,
                    annual_fee,
                )
            )
    elif period_month is not None:
        monthly_date, provisional = monthly_revenue_recognition_date(period_month, today=today)
        monthly_fee = money(pricing_plan.monthly_fixed_fee)
        if monthly_fee:
            amounts.append(
                RevenueAmount(
                    0,
                    "SIGEN",
                    "monthly_subscription",
                    monthly_fee,
                    monthly_date,
                    monthly_fee,
                    provisional_fx=provisional,
                )
            )
    return amounts + usage_revenue_amounts(client_usage, pricing_plan)


def usage_revenue_amounts(
    client_usage: Iterable[UsageEvent],
    pricing_plan: PricingPlan,
) -> list[RevenueAmount]:
    amounts: list[RevenueAmount] = []
    included_remaining = {
        "saremi.document_validation": pricing_plan.included_documents,
        "saremi.ine_validation": pricing_plan.included_validations,
        "graphos.query": pricing_plan.included_graph_queries,
        "graphos.case_analysis": pricing_plan.included_graph_queries,
        "blockchain.asiento_registration": pricing_plan.included_blockchain_transactions,
        "blockchain.certificate_issued": pricing_plan.included_blockchain_transactions,
    }
    for event in client_usage:
        price_field = EVENT_PRICE_FIELDS.get(event.event_type)
        if not price_field:
            continue
        included = Decimal(str(included_remaining.get(event.event_type, 0)))
        billable_quantity = max(money(event.quantity) - included, Decimal("0"))
        included_remaining[event.event_type] = max(int(included - money(event.quantity)), 0)
        revenue = billable_quantity * money(getattr(pricing_plan, price_field))
        if revenue:
            amounts.append(
                RevenueAmount(
                    event.client_id,
                    _service_line(event.event_type),
                    "usage",
                    revenue,
                    event.event_timestamp.date(),
                    revenue,
                )
            )
    return amounts


def monthly_revenue_recognition_date(period_month: date, *, today: date | None = None) -> tuple[date, bool]:
    from app.domain.cost_engine import mexico_today

    current_date = today or mexico_today()
    if (period_month.year, period_month.month) == (current_date.year, current_date.month):
        return current_date, True
    month_end = date(
        period_month.year,
        period_month.month,
        calendar.monthrange(period_month.year, period_month.month)[1],
    )
    return month_end, False


def _service_line(event_type: str) -> str:
    if event_type.startswith("saremi"):
        return "SAREMI"
    if event_type.startswith("graphos"):
        return "Graphos"
    if event_type.startswith("blockchain"):
        return "Blockchain / BaaS"
    return "Other"


def _setup_fee_for_month(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription,
    period_month: date,
) -> Decimal:
    if subscription.start_date.year == period_month.year and subscription.start_date.month == period_month.month:
        return money(pricing_plan.setup_fee)
    return Decimal("0")


def _annual_fee_for_month(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription,
    period_month: date,
) -> Decimal:
    if period_month < subscription.start_date:
        return Decimal("0")
    if subscription.start_date.month == period_month.month:
        return money(pricing_plan.annual_fee)
    return Decimal("0")
