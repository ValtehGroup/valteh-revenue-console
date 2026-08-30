from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import BASE_DIR
from app.data.client_repository import (
    ClientCommand,
    ClientRepository,
    ClientValidationError,
    ContractTermsOverride,
)
from app.data.schemas import Base, ClientSubscriptionORM, PricingPlanORM, UsageEventORM
from app.data.seed_data import ensure_client_seeded, ensure_usage_seeded
from app.domain.models import ClientSubscription, PricingPlan, UsageEvent
from app.domain.pricing_simulator import crossover_documents
from app.domain.revenue_engine import calculate_client_revenue, revenue_amounts


def _repository_with_plan(plan: PricingPlanORM):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(plan)
    return ClientRepository(factory), factory


def _core_plan(plan_id: int = 7) -> PricingPlanORM:
    return PricingPlanORM(
        id=plan_id,
        name="Core",
        plan_code="SAREMI_CORE",
        version=1,
        service_line="saremi_platform",
        monthly_fixed_fee=Decimal("6999"),
        included_documents=1000,
        price_per_document=Decimal("9"),
        setup_fee=Decimal("9999"),
        minimum_setup_fee=Decimal("6999"),
        annual_fee=0,
        one_time_fee=0,
        effective_from=date(2026, 9, 1),
    )


def test_seed_catalog_has_exact_saremi_economics_and_visibility(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ensure_client_seeded(
        BASE_DIR / "data" / "seed_clients.csv",
        BASE_DIR / "data" / "seed_pricing_plans.csv",
        BASE_DIR / "data" / "seed_client_subscriptions.csv",
        factory,
    )
    ensure_usage_seeded(BASE_DIR / "data" / "seed_usage.csv", factory)
    monkeypatch.setattr("app.data.database.SessionLocal", factory)

    from app.data.repositories import SeedRepository

    repo = SeedRepository()
    plans = {plan.plan_code: plan for plan in repo.pricing_plans()}
    assert (plans["SAREMI_CORE"].monthly_fixed_fee, plans["SAREMI_CORE"].included_documents) == (
        Decimal("6999"),
        1000,
    )
    assert (plans["SAREMI_SCALE"].monthly_fixed_fee, plans["SAREMI_SCALE"].price_per_document) == (
        Decimal("11999"),
        Decimal("6.5"),
    )
    assert plans["SAREMI_SCALE"].featured is True
    assert not plans["SAREMI_SCALE"].featured_label
    assert {plans[code].setup_fee for code in ("SAREMI_CORE", "SAREMI_SCALE", "SAREMI_ENTERPRISE")} == {Decimal("9999")}
    assert {plans[code].minimum_setup_fee for code in ("SAREMI_CORE", "SAREMI_SCALE", "SAREMI_ENTERPRISE")} == {
        Decimal("9999")
    }
    assert plans["SAREMI_ENTERPRISE"].monthly_fixed_fee is None
    assert plans["SAREMI_ENTERPRISE"].included_documents is None
    assert plans["SAREMI_API_10K"].status == "active"
    assert plans["SAREMI_API_10K"].assignable is True
    assert plans["SAREMI_API_10K"].assignment_requires_approval is False
    assert {plan.plan_code for plan in repo.pricing_plans(catalog_only=True, assignable_only=True)} == {
        "SAREMI_CORE",
        "SAREMI_SCALE",
        "SAREMI_API_1K",
        "SAREMI_API_2_5K",
        "SAREMI_API_10K",
    }
    assert not {"LEGACY_SIGEN_GO", "LEGACY_SIGEN_PLUS", "LEGACY_SIGEN_PRO"} & {
        plan.plan_code for plan in repo.pricing_plans(catalog_only=True)
    }
    with factory() as session:
        demo_usage = session.execute(
            select(UsageEventORM.data_origin, UsageEventORM.environment, UsageEventORM.is_billable).distinct()
        ).all()
    assert demo_usage == [("demo", "sandbox", False)]


def test_contract_snapshots_catalog_and_overrides_without_mutating_plan() -> None:
    repository, factory = _repository_with_plan(_core_plan())
    client = repository.create_client(
        ClientCommand(
            "Negotiated client",
            "notary",
            "2026-09-01",
            pricing_plan_id=7,
            contract_terms=ContractTermsOverride(
                monthly_fee="6500",
                overage_price="8",
                setup_fee="6500",
                setup_disposition="charged",
                discount_reason="Launch agreement",
                approved_by="commercial@example.com",
            ),
        )
    )

    with factory() as session:
        plan = session.get(PricingPlanORM, 7)
        agreement = session.scalar(select(ClientSubscriptionORM).where(ClientSubscriptionORM.client_id == client.id))
    assert agreement.contracted_monthly_fee == Decimal("6500")
    assert agreement.contracted_overage_price == Decimal("8")
    assert agreement.contracted_included_documents == 1000
    assert plan.monthly_fixed_fee == Decimal("6999")
    assert plan.price_per_document == Decimal("9")


@pytest.mark.parametrize("disposition", ["included", "waived", "not_applicable"])
def test_unbilled_setup_treatments_snapshot_zero(disposition: str) -> None:
    repository, factory = _repository_with_plan(_core_plan())
    client = repository.create_client(
        ClientCommand(
            "Setup client",
            "notary",
            "2026-09-01",
            pricing_plan_id=7,
            contract_terms=ContractTermsOverride(setup_disposition=disposition),
        )
    )
    with factory() as session:
        agreement = session.scalar(select(ClientSubscriptionORM).where(ClientSubscriptionORM.client_id == client.id))
    assert agreement.contracted_setup_fee == 0


def test_setup_below_minimum_requires_reason_and_approval() -> None:
    repository, _factory = _repository_with_plan(_core_plan())
    with pytest.raises(ClientValidationError, match="reason and an approver"):
        repository.create_client(
            ClientCommand(
                "Unapproved client",
                "notary",
                "2026-09-01",
                pricing_plan_id=7,
                contract_terms=ContractTermsOverride(setup_fee="6000", setup_disposition="charged"),
            )
        )


def test_new_billing_cycles_are_temporarily_limited_to_day_one() -> None:
    repository, _factory = _repository_with_plan(_core_plan())
    with pytest.raises(ClientValidationError, match="first day"):
        repository.create_client(ClientCommand("Mid-cycle", "notary", "2026-09-15", pricing_plan_id=7))


def test_n38_one_time_revenue_has_no_mrr_or_missing_usage_overage() -> None:
    plan = PricingPlan(
        id=5,
        name="Notaría 38 Pilot",
        plan_code="SAREMI_PILOT_N38_2026",
        service_line="pilot",
        pricing_model="one_time",
        monthly_fixed_fee=0,
        one_time_fee=5000,
        included_documents=500,
        price_per_document=0,
    )
    agreement = ClientSubscription(
        id=1,
        client_id=1,
        pricing_plan_id=5,
        start_date=date(2026, 8, 1),
        contracted_monthly_fee=0,
        contracted_included_documents=500,
        contracted_overage_price=0,
        contracted_setup_fee=0,
        setup_disposition="included",
        contracted_one_time_fee=5000,
        usage_data_status="pending",
    )
    assert calculate_client_revenue([], plan, agreement, date(2026, 8, 1)) == 5000
    assert calculate_client_revenue([], plan, agreement, date(2026, 9, 1)) == 0
    assert [amount.revenue_type for amount in revenue_amounts([], plan, agreement, date(2026, 8, 1))] == [
        "pilot_one_time"
    ]


def test_canonical_documents_dedupe_retries_and_ignore_nonproduction() -> None:
    plan = PricingPlan(
        id=7,
        name="Core",
        service_line="saremi_platform",
        monthly_fixed_fee=6999,
        included_documents=1,
        price_per_document=9,
    )
    agreement = ClientSubscription(
        id=1,
        client_id=1,
        pricing_plan_id=7,
        start_date=date(2026, 9, 1),
        contracted_monthly_fee=6999,
        contracted_included_documents=1,
        contracted_overage_price=9,
        usage_data_status="available",
    )

    def event(event_id: int, unit_id: str, **overrides) -> UsageEvent:
        values = {
            "id": event_id,
            "client_id": 1,
            "service_code": "saremi",
            "event_type": "saremi.processed_document",
            "quantity": 1,
            "unit": "document",
            "event_timestamp": datetime(2026, 9, event_id),
            "source_system": "saremi",
            "billable_unit_id": unit_id,
        }
        values.update(overrides)
        return UsageEvent(**values)

    events = [
        event(1, "doc-1"),
        event(2, "doc-1"),  # duplicate technical delivery
        event(3, "doc-2"),
        event(4, "retry", is_billable=False),
        event(5, "sandbox", environment="sandbox"),
    ]
    amounts = revenue_amounts(events, plan, agreement, date(2026, 9, 1))
    assert [(amount.revenue_type, amount.amount_mxn) for amount in amounts] == [
        ("platform_subscription", Decimal("6999")),
        ("document_overage", Decimal("9")),
    ]


def test_expected_plan_crossovers() -> None:
    core = PricingPlan(id=7, name="Core", monthly_fixed_fee=6999, included_documents=1000, price_per_document=9)
    scale = PricingPlan(id=8, name="Scale", monthly_fixed_fee=11999, included_documents=2500, price_per_document=6.5)
    api_1k = PricingPlan(id=10, name="API 1K", monthly_fixed_fee=4499, included_documents=1000, price_per_document=5)
    api_2_5k = PricingPlan(
        id=11, name="API 2.5K", monthly_fixed_fee=8999, included_documents=2500, price_per_document=4
    )
    api_10k = PricingPlan(
        id=12, name="API 10K", monthly_fixed_fee=28999, included_documents=10000, price_per_document=3.2
    )

    assert crossover_documents(core, scale) == 1556
    assert crossover_documents(api_1k, api_2_5k) == 1900
    assert crossover_documents(api_2_5k, api_10k) == 7500
