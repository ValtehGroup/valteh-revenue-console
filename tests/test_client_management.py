from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import BASE_DIR
from app.data.client_repository import (
    ClientCommand,
    ClientConcurrencyError,
    ClientReferenceConflictError,
    ClientRepository,
    ClientUpdateCommand,
    ClientValidationError,
)
from app.data.schemas import Base, ClientORM, ClientSubscriptionORM, PricingPlanORM, UsageEventORM
from app.data.seed_data import ensure_client_seeded
from app.main import create_app


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return ClientRepository(factory), factory


def client_command(**overrides) -> ClientCommand:
    values = {
        "name": "New client",
        "client_type": "notary",
        "start_date": "2026-08-01",
        "notes": "Initial onboarding",
    }
    values.update(overrides)
    return ClientCommand(**values)


def test_client_seed_is_idempotent(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'clients.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    first = ensure_client_seeded(
        BASE_DIR / "data" / "seed_clients.csv",
        BASE_DIR / "data" / "seed_pricing_plans.csv",
        BASE_DIR / "data" / "seed_client_subscriptions.csv",
        factory,
    )
    second = ensure_client_seeded(
        BASE_DIR / "data" / "seed_clients.csv",
        BASE_DIR / "data" / "seed_pricing_plans.csv",
        BASE_DIR / "data" / "seed_client_subscriptions.csv",
        factory,
    )

    assert first == 3
    assert second == 0
    assert [client.client_code for client in ClientRepository(factory).list_clients()] == [
        "test_0003",
        "test_0002",
        "client_0001",
    ]
    assert ClientRepository(factory).get_client_by_code("test_0002").id == 2
    with factory() as session:
        ad_hoc_plan = session.get(PricingPlanORM, 5)
    assert ad_hoc_plan.name == "Notaría 38 Pilot (Ad hoc)"
    assert ad_hoc_plan.dedicated_client_id == 1
    assert ad_hoc_plan.setup_fee == 5000
    assert ad_hoc_plan.included_documents == 500
    with factory() as session:
        notaria_subscription = session.scalar(select(ClientSubscriptionORM).where(ClientSubscriptionORM.client_id == 1))
    assert notaria_subscription.pricing_plan_id == 5
    assert notaria_subscription.start_date == date(2026, 8, 1)


def test_create_generates_public_code_and_timestamps(repository) -> None:
    client_repository, _factory = repository

    created = client_repository.create_client(client_command())

    assert created.client_code == "client_0001"
    assert created.status == "active"
    assert created.created_at is not None
    assert created.updated_at == created.created_at
    assert client_repository.get_client_by_code("client_0001").id == created.id

    with pytest.raises(ValidationError, match="frozen"):
        created.client_code = "client_9999"


def test_create_with_pricing_plan_creates_initial_subscription_atomically(repository) -> None:
    client_repository, factory = repository
    with factory.begin() as session:
        session.add(PricingPlanORM(id=7, name="SIGEN Go"))

    created = client_repository.create_client(client_command(pricing_plan_id=7))

    with factory() as session:
        subscription = session.scalar(
            select(ClientSubscriptionORM).where(ClientSubscriptionORM.client_id == created.id)
        )
    assert subscription is not None
    assert subscription.pricing_plan_id == 7
    assert subscription.start_date == created.start_date
    assert subscription.status == "active"


def test_missing_pricing_plan_rolls_back_client_creation(repository) -> None:
    client_repository, factory = repository

    with pytest.raises(ClientValidationError, match="no longer available"):
        client_repository.create_client(client_command(pricing_plan_id=999))

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClientORM)) == 0


def test_dedicated_pricing_plan_cannot_be_reused_for_a_new_client(repository) -> None:
    client_repository, factory = repository
    with factory.begin() as session:
        session.add(PricingPlanORM(id=5, name="Notaría 38 Pilot (Ad hoc)", dedicated_client_id=1))

    with pytest.raises(ClientValidationError, match="Client-specific"):
        client_repository.create_client(client_command(pricing_plan_id=5))

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClientORM)) == 0


def test_change_pricing_plan_preserves_prior_subscription_history(repository) -> None:
    client_repository, factory = repository
    with factory.begin() as session:
        session.add_all(
            [
                PricingPlanORM(id=1, name="Pilot"),
                PricingPlanORM(id=2, name="SIGEN Go"),
            ]
        )
    created = client_repository.create_client(client_command(start_date="2026-07-01", pricing_plan_id=1))

    replacement = client_repository.change_pricing_plan(
        created.id,
        2,
        "2026-09-01",
        created.updated_at,
    )

    with factory() as session:
        subscriptions = session.scalars(
            select(ClientSubscriptionORM)
            .where(ClientSubscriptionORM.client_id == created.id)
            .order_by(ClientSubscriptionORM.start_date)
        ).all()
    assert replacement.pricing_plan_id == 2
    assert replacement.start_date == date(2026, 9, 1)
    assert [(item.pricing_plan_id, item.start_date, item.end_date, item.status) for item in subscriptions] == [
        (1, date(2026, 7, 1), date(2026, 8, 31), "inactive"),
        (2, date(2026, 9, 1), None, "active"),
    ]
    assert client_repository.get_client(created.id).client_code == created.client_code


def test_dedicated_pricing_plan_can_only_be_assigned_to_its_client(repository) -> None:
    client_repository, factory = repository
    with factory.begin() as session:
        session.add_all(
            [
                PricingPlanORM(id=1, name="Pilot"),
                PricingPlanORM(id=5, name="Notaría 38 Pilot (Ad hoc)", dedicated_client_id=1),
            ]
        )
    notaria_38 = client_repository.create_client(
        client_command(name="Notaría 38", start_date="2026-07-01", pricing_plan_id=1)
    )
    other_client = client_repository.create_client(
        client_command(name="Other client", start_date="2026-07-01", pricing_plan_id=1)
    )

    replacement = client_repository.change_pricing_plan(
        notaria_38.id,
        5,
        "2026-09-01",
        notaria_38.updated_at,
    )
    assert replacement.pricing_plan_id == 5

    with pytest.raises(ClientValidationError, match="dedicated to another client"):
        client_repository.change_pricing_plan(
            other_client.id,
            5,
            "2026-09-01",
            other_client.updated_at,
        )


def test_change_pricing_plan_rejects_overlap_without_altering_history(repository) -> None:
    client_repository, factory = repository
    with factory.begin() as session:
        session.add_all(
            [
                PricingPlanORM(id=1, name="Pilot"),
                PricingPlanORM(id=2, name="SIGEN Go"),
            ]
        )
    created = client_repository.create_client(client_command(start_date="2026-07-01", pricing_plan_id=1))

    with pytest.raises(ClientValidationError, match="start dates"):
        client_repository.change_pricing_plan(created.id, 2, "2026-07-01", created.updated_at)

    with factory() as session:
        subscription = session.scalar(
            select(ClientSubscriptionORM).where(ClientSubscriptionORM.client_id == created.id)
        )
    assert subscription.pricing_plan_id == 1
    assert subscription.end_date is None
    assert subscription.status == "active"


def test_update_preserves_code_and_created_at_but_advances_updated_at(repository) -> None:
    client_repository, _factory = repository
    created = client_repository.create_client(client_command())

    updated = client_repository.update_client(
        created.id,
        ClientUpdateCommand("Renamed client", "enterprise", "2026-07-01", "Updated"),
        created.updated_at,
    )

    assert updated.client_code == created.client_code
    assert updated.created_at == created.created_at
    assert updated.updated_at > created.updated_at
    assert updated.name == "Renamed client"


def test_stale_update_is_rejected(repository) -> None:
    client_repository, _factory = repository
    created = client_repository.create_client(client_command())
    client_repository.update_client(
        created.id,
        ClientUpdateCommand(created.name, created.client_type, created.start_date, "First writer"),
        created.updated_at,
    )

    with pytest.raises(ClientConcurrencyError, match="another user"):
        client_repository.update_client(
            created.id,
            ClientUpdateCommand(created.name, created.client_type, created.start_date, "Stale writer"),
            created.updated_at,
        )


def test_deactivation_preserves_client_usage_and_closes_subscription(repository) -> None:
    client_repository, factory = repository
    created = client_repository.create_client(client_command(start_date="2026-07-01"))
    with factory.begin() as session:
        session.add(
            UsageEventORM(
                id=1,
                client_id=created.id,
                service_code="saremi",
                event_type="saremi.document_validation",
                quantity=1,
                unit="document",
                event_timestamp=datetime(2026, 7, 15),
                source_system="saremi",
            )
        )
        session.add(PricingPlanORM(id=1, name="Pilot"))
        session.add(
            ClientSubscriptionORM(
                id=1,
                client_id=created.id,
                pricing_plan_id=1,
                start_date=date(2026, 7, 1),
                status="active",
            )
        )

    deactivated = client_repository.deactivate_client(created.id, "2026-07-31", created.updated_at)

    with factory() as session:
        usage_count = session.scalar(select(func.count()).select_from(UsageEventORM))
        subscription = session.get(ClientSubscriptionORM, 1)
    assert deactivated.status == "inactive"
    assert deactivated.end_date == date(2026, 7, 31)
    assert usage_count == 1
    assert subscription.status == "inactive"
    assert subscription.end_date == date(2026, 7, 31)
    assert not hasattr(client_repository, "delete_client")


def test_invalid_deactivation_date_is_rejected(repository) -> None:
    client_repository, _factory = repository
    created = client_repository.create_client(client_command(start_date="2026-08-01"))

    with pytest.raises(ClientValidationError, match="start date"):
        client_repository.deactivate_client(created.id, "2026-07-31", created.updated_at)


def test_reactivation_clears_end_date_without_recreating_subscription(repository) -> None:
    client_repository, factory = repository
    created = client_repository.create_client(client_command(start_date="2026-07-01"))
    deactivated = client_repository.deactivate_client(created.id, "2026-07-31", created.updated_at)

    reactivated = client_repository.reactivate_client(deactivated.id, deactivated.updated_at)

    with factory() as session:
        subscription_count = session.scalar(select(func.count()).select_from(ClientSubscriptionORM))
    assert reactivated.status == "active"
    assert reactivated.end_date is None
    assert reactivated.client_code == created.client_code
    assert reactivated.created_at == created.created_at
    assert reactivated.updated_at > deactivated.updated_at
    assert subscription_count == 0


def test_external_references_are_source_scoped_and_resolvable(repository) -> None:
    client_repository, _factory = repository
    created = client_repository.create_client(client_command())

    saremi = client_repository.add_reference(created.id, "SAREMI", "tenant-42")
    baas = client_repository.add_reference(created.id, "baas-qro", "tenant-42")

    assert saremi.source_system == "saremi"
    assert baas.source_system == "baas-qro"
    assert client_repository.resolve_client_reference("saremi", "tenant-42") == created.id
    assert client_repository.resolve_client_reference("graphos", "unknown") is None


def test_external_reference_conflict_rolls_back_atomic_client_create(repository) -> None:
    client_repository, _factory = repository
    first = client_repository.create_client(
        client_command(source_system="saremi", external_client_reference="tenant-42")
    )

    with pytest.raises(ClientReferenceConflictError):
        client_repository.create_client(
            client_command(
                name="Conflicting client",
                source_system="saremi",
                external_client_reference="tenant-42",
            )
        )

    assert [client.id for client in client_repository.list_clients()] == [first.id]


def test_deactivated_reference_is_retained_but_no_longer_resolves(repository) -> None:
    client_repository, _factory = repository
    created = client_repository.create_client(client_command())
    reference = client_repository.add_reference(created.id, "graphos", "org-7")

    client_repository.deactivate_reference(reference.id)

    assert client_repository.resolve_client_reference("graphos", "org-7") is None
    assert client_repository.list_references(created.id)[0].enabled is False


def test_multiple_creations_do_not_duplicate_codes(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def create(index: int) -> str:
        return ClientRepository(factory).create_client(client_command(name=f"Client {index}")).client_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        codes = list(executor.map(create, range(8)))

    assert len(codes) == len(set(codes)) == 8
    assert all(code.startswith("client_") for code in codes)


def test_client_migration_backfills_codes_without_changing_primary_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "prior-clients.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE clients (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, "
                "client_type VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL, "
                "start_date DATE NOT NULL, notes TEXT)"
            )
        )
        for client_id in (1, 2, 3):
            connection.execute(
                sa.text(
                    "INSERT INTO clients (id, name, client_type, status, start_date) "
                    "VALUES (:id, :name, 'notary', 'active', '2026-01-01')"
                ),
                {"id": client_id, "name": f"Client {client_id}"},
            )

    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT id, client_code FROM clients ORDER BY id")).all()
    assert rows == [(1, "client_0001"), (2, "test_0002"), (3, "test_0003")]
    checks = {constraint["name"] for constraint in sa.inspect(engine).get_check_constraints("clients")}
    assert {"ck_clients_status", "ck_clients_dates"} <= checks


def test_client_code_format_grows_beyond_four_digits(repository) -> None:
    _client_repository, factory = repository
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            ClientORM(
                id=10000,
                client_code="client_10000",
                name="Large ID",
                client_type="enterprise",
                status="active",
                start_date=date(2026, 1, 1),
                created_at=now,
                updated_at=now,
            )
        )
    assert ClientRepository(factory).get_client(10000).client_code == "client_10000"


def test_client_callbacks_register_without_delete_or_duplicate_outputs() -> None:
    app = create_app()

    assert any("clients-table.data" in key for key in app.callback_map)
    assert any("client-detail-client-filter.options" in key for key in app.callback_map)
    assert all("delete" not in key.lower() for key in app.callback_map)
