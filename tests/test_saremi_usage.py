from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.saremi_usage_repository import SaremiUsageRepository
from app.data.schemas import Base
from app.domain.saremi_usage import SaremiUsageEvent, classify_saremi_event
from app.pages.usage import _saremi_status_message

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


def _event(**changes) -> SaremiUsageEvent:
    values = {
        "event_id": "ue_1",
        "verification_id": "ver_1",
        "institution_id": "inst_1",
        "document_type": "INE",
        "operation": "document_verification",
        "status": "verified",
        "created_at": NOW,
        "completed_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return SaremiUsageEvent.model_validate(values)


def test_console_policy_keeps_missing_environment_unresolved():
    result = classify_saremi_event(_event(), client_id=1, billable_unit_confirmed=True)
    assert result.classification_status == "unresolved"
    assert result.revenue_environment is None


def test_console_read_model_exposes_no_raw_payload():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        SaremiUsageRepository.upsert_events(
            session,
            [_event(future_field="audit-only")],
            observed_at=NOW,
            billable_unit_confirmed=False,
        )

    repository = SaremiUsageRepository(factory)
    rows = repository.list_events()
    assert rows[0]["source_status"] == "verified"
    assert "raw_payload_json" not in rows[0]
    assert "future_field" not in rows[0]
    assert "institution_name" not in rows[0]


def test_console_status_message_distinguishes_not_started():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    status = SaremiUsageRepository(sessionmaker(engine)).status()
    assert "has not started" in _saremi_status_message(status)
