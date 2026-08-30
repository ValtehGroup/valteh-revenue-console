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
    "saremi.processed_document": "price_per_document",
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
        client_usage, pricing_plan, subscription
    )


def calculate_subscription_revenue(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
    period_month: date | None = None,
) -> Decimal:
    """Calculate setup, annual, and monthly fixed fees for one client and period."""

    revenue = money(_contract_value(subscription, "contracted_monthly_fee", pricing_plan.monthly_fixed_fee))
    if subscription and period_month:
        revenue += _setup_fee_for_month(pricing_plan, subscription, period_month)
        revenue += _annual_fee_for_month(pricing_plan, subscription, period_month)
        revenue += _one_time_fee_for_month(pricing_plan, subscription, period_month)
    return revenue


def calculate_usage_revenue(
    client_usage: Iterable[UsageEvent],
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
) -> Decimal:
    """Calculate billable usage revenue after included quantities."""

    if subscription is not None and not _usage_is_available(subscription):
        return Decimal("0")
    return sum(
        (amount.amount_mxn for amount in usage_revenue_amounts(client_usage, pricing_plan, subscription)),
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
        monthly_fee = money(_contract_value(subscription, "contracted_monthly_fee", pricing_plan.monthly_fixed_fee))
        if monthly_fee:
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    _plan_service_line(pricing_plan),
                    _subscription_revenue_type(pricing_plan),
                    monthly_fee,
                    monthly_date,
                    monthly_fee,
                    provisional_fx=provisional,
                )
            )
        setup_fee = money(_contract_value(subscription, "contracted_setup_fee", pricing_plan.setup_fee))
        if (
            setup_fee
            and (subscription.setup_disposition == "charged" or subscription.contracted_setup_fee is None)
            and subscription.start_date.year == period_month.year
            and subscription.start_date.month == period_month.month
        ):
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    _plan_service_line(pricing_plan),
                    "setup_implementation" if pricing_plan.service_line != "legacy_sigen" else "setup",
                    setup_fee,
                    subscription.start_date,
                    setup_fee,
                )
            )
        annual_fee = money(_contract_value(subscription, "contracted_annual_fee", pricing_plan.annual_fee))
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
                    _plan_service_line(pricing_plan),
                    "annual",
                    annual_fee,
                    anniversary,
                    annual_fee,
                )
            )
        one_time_fee = money(_contract_value(subscription, "contracted_one_time_fee", pricing_plan.one_time_fee))
        if (
            one_time_fee
            and subscription.start_date.year == period_month.year
            and subscription.start_date.month == period_month.month
        ):
            amounts.append(
                RevenueAmount(
                    subscription.client_id,
                    _plan_service_line(pricing_plan),
                    "pilot_one_time",
                    one_time_fee,
                    subscription.start_date,
                    one_time_fee,
                )
            )
    elif period_month is not None:
        monthly_date, provisional = monthly_revenue_recognition_date(period_month, today=today)
        monthly_fee = money(pricing_plan.monthly_fixed_fee)
        if monthly_fee:
            amounts.append(
                RevenueAmount(
                    0,
                    _plan_service_line(pricing_plan),
                    _subscription_revenue_type(pricing_plan),
                    monthly_fee,
                    monthly_date,
                    monthly_fee,
                    provisional_fx=provisional,
                )
            )
    if subscription is not None and not _usage_is_available(subscription):
        return amounts
    return amounts + usage_revenue_amounts(client_usage, pricing_plan, subscription)


def usage_revenue_amounts(
    client_usage: Iterable[UsageEvent],
    pricing_plan: PricingPlan,
    subscription: ClientSubscription | None = None,
) -> list[RevenueAmount]:
    amounts: list[RevenueAmount] = []
    seen_billable_units: set[str] = set()
    included_remaining = {
        "saremi_document": (
            subscription.contracted_included_documents
            if subscription is not None and subscription.contracted_included_documents is not None
            else pricing_plan.included_documents or 0
        ),
        "saremi.ine_validation": pricing_plan.included_validations,
        "graphos.query": pricing_plan.included_graph_queries,
        "graphos.case_analysis": pricing_plan.included_graph_queries,
        "blockchain.asiento_registration": pricing_plan.included_blockchain_transactions,
        "blockchain.certificate_issued": pricing_plan.included_blockchain_transactions,
    }
    for event in client_usage:
        if event.data_origin != "production" or event.environment != "production" or not event.is_billable:
            continue
        if event.billable_unit_id is not None:
            if event.billable_unit_id in seen_billable_units:
                continue
            seen_billable_units.add(event.billable_unit_id)
        price_field = EVENT_PRICE_FIELDS.get(event.event_type)
        if not price_field:
            continue
        bucket = (
            "saremi_document"
            if event.event_type in {"saremi.processed_document", "saremi.document_validation"}
            else event.event_type
        )
        included = Decimal(str(included_remaining.get(bucket, 0)))
        billable_quantity = max(money(event.quantity) - included, Decimal("0"))
        included_remaining[bucket] = max(int(included - money(event.quantity)), 0)
        unit_price = (
            subscription.contracted_overage_price
            if subscription is not None
            and subscription.contracted_overage_price is not None
            and bucket == "saremi_document"
            else getattr(pricing_plan, price_field)
        )
        revenue = billable_quantity * money(unit_price)
        if revenue:
            amounts.append(
                RevenueAmount(
                    event.client_id,
                    (
                        _plan_service_line(pricing_plan)
                        if bucket == "saremi_document"
                        else _service_line(event.event_type)
                    ),
                    (
                        "document_overage"
                        if bucket == "saremi_document"
                        and pricing_plan.service_line in {"saremi_platform", "saremi_api", "pilot"}
                        else "usage"
                    ),
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


def _plan_service_line(pricing_plan: PricingPlan) -> str:
    return {
        "saremi_platform": "SAREMI Platform",
        "saremi_api": "SAREMI API",
        "pilot": "SAREMI Pilot",
        "legacy_sigen": "SIGEN",
    }.get(pricing_plan.service_line, pricing_plan.service_line)


def _subscription_revenue_type(pricing_plan: PricingPlan) -> str:
    return {
        "saremi_platform": "platform_subscription",
        "saremi_api": "api_subscription",
    }.get(pricing_plan.service_line, "monthly_subscription")


def _usage_is_available(subscription: ClientSubscription) -> bool:
    if subscription.usage_data_status == "available":
        return True
    return (
        subscription.contracted_monthly_fee is None
        and subscription.contracted_included_documents is None
        and subscription.contracted_overage_price is None
    )


def _setup_fee_for_month(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription,
    period_month: date,
) -> Decimal:
    if (
        subscription.setup_disposition == "charged"
        and subscription.start_date.year == period_month.year
        and subscription.start_date.month == period_month.month
    ):
        return money(_contract_value(subscription, "contracted_setup_fee", pricing_plan.setup_fee))
    if subscription.contracted_setup_fee is None and (
        subscription.start_date.year == period_month.year and subscription.start_date.month == period_month.month
    ):
        return money(pricing_plan.setup_fee or 0)
    return Decimal("0")


def _annual_fee_for_month(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription,
    period_month: date,
) -> Decimal:
    if period_month < subscription.start_date:
        return Decimal("0")
    if subscription.start_date.month == period_month.month:
        return money(_contract_value(subscription, "contracted_annual_fee", pricing_plan.annual_fee))
    return Decimal("0")


def _one_time_fee_for_month(
    pricing_plan: PricingPlan,
    subscription: ClientSubscription,
    period_month: date,
) -> Decimal:
    if subscription.start_date.year == period_month.year and subscription.start_date.month == period_month.month:
        return money(_contract_value(subscription, "contracted_one_time_fee", pricing_plan.one_time_fee))
    return Decimal("0")


def _contract_value(subscription: ClientSubscription | None, field: str, catalog_value) -> Decimal:
    if subscription is None:
        return Decimal(str(catalog_value or 0))
    value = getattr(subscription, field)
    return Decimal(str(catalog_value or 0)) if value is None else Decimal(str(value))
