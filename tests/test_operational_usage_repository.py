from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data import database
from app.data.repositories import SeedRepository
from app.data.schemas import Base, ClientORM, ImportedOperationalEventORM, UsageEventORM
from app.data.seed_data import ensure_usage_seeded


def test_console_usage_queries_include_api_normalized_sql_rows(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            ClientORM(
                id=1,
                client_code="client_0001",
                name="Operational client",
                client_type="enterprise",
                status="active",
                start_date=date(2026, 1, 1),
                created_at=now,
                updated_at=now,
            )
        )
        raw = ImportedOperationalEventORM(
            source_system="baas-qro",
            source_event_id="source-event-1",
            event_type="blockchain.property_minted",
            event_category="blockchain",
            occurred_at=datetime(2026, 7, 15, 10, 0),
            received_at=datetime(2026, 7, 15, 10, 1),
            status="succeeded",
            quantity=Decimal("1"),
            unit="property",
            import_status="normalized",
        )
        session.add(raw)
        session.flush()
        session.add(
            UsageEventORM(
                client_id=1,
                service_code="blockchain",
                event_type="blockchain.folio_mint",
                quantity=Decimal("1"),
                unit="property",
                event_timestamp=datetime(2026, 7, 15, 10, 0),
                source_system="baas-qro",
                external_reference_id="source-event-1",
                metadata_json='{"provenance":{"source_event_id":"source-event-1"}}',
                imported_event_id=raw.id,
            )
        )

    monkeypatch.setattr(database, "SessionLocal", factory)
    repository = SeedRepository()
    monkeypatch.setattr(repository, "active_clients", lambda _month: [SimpleNamespace(id=1)])

    events = repository.usage_for_month("2026-07")

    assert len(events) == 1
    assert events[0].event_type == "blockchain.folio_mint"
    assert events[0].imported_event_id is not None
    assert events[0].metadata_json["provenance"]["source_event_id"] == "source-event-1"


def test_historical_usage_seed_is_idempotent_sql_data() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    seed_path = Path(__file__).resolve().parents[1] / "data" / "seed_usage.csv"

    first = ensure_usage_seeded(seed_path, factory)
    second = ensure_usage_seeded(seed_path, factory)

    with factory() as session:
        row_count = session.scalar(select(func.count()).select_from(UsageEventORM))
    assert first == 10
    assert second == 0
    assert row_count == 10
