from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.anthropic_assignment_repository import (
    AnthropicAssignmentRepository,
    AnthropicKeyAssignmentCommand,
)
from app.data.schemas import Base, ClientORM


def _repository() -> tuple[AnthropicAssignmentRepository, sessionmaker]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add_all(
            [
                ClientORM(
                    id=1,
                    client_code="client_0001",
                    name="SAREMI",
                    client_type="platform",
                    status="active",
                    start_date=date(2026, 1, 1),
                    created_at=now,
                    updated_at=now,
                ),
                ClientORM(
                    id=2,
                    client_code="client_0002",
                    name="Notaria 38",
                    client_type="notary",
                    status="active",
                    start_date=date(2026, 1, 1),
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
    return AnthropicAssignmentRepository(factory), factory


def test_assignment_can_be_saved_reassigned_and_removed() -> None:
    repository, _factory = _repository()

    repository.save_assignments([AnthropicKeyAssignmentCommand("apikey_abc123", "development", 1)])
    assert [(row.environment, row.client_id) for row in repository.list_assignments()] == [("development", 1)]

    repository.save_assignments([AnthropicKeyAssignmentCommand("apikey_abc123", "production", 2)])
    assert [(row.environment, row.client_id) for row in repository.list_assignments()] == [("production", 2)]

    repository.save_assignments([AnthropicKeyAssignmentCommand("apikey_abc123", None, None)])
    assert repository.list_assignments() == []
    periods = repository.list_assignment_periods()
    assert [(period.environment, period.client_id) for period in periods] == [("development", 1)]
    assert periods[0].effective_from == date(2026, 7, 1)
    assert periods[0].effective_to == date.today() - timedelta(days=1)
