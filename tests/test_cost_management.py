from datetime import UTC, date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import BASE_DIR
from app.data.cost_repository import (
    CostCommand,
    CostConcurrencyError,
    CostRepository,
    CostValidationError,
    MetadataCommand,
)
from app.data.schemas import Base
from app.data.seed_data import ensure_cost_seeded


@pytest.fixture
def repository() -> CostRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return CostRepository(factory)


def command(**overrides) -> CostCommand:
    values = {
        "name": "Managed server",
        "provider": "Hetzner",
        "category": "Infrastructure",
        "service_line": "Shared",
        "cost_type": "fixed",
        "charge_basis": "flat",
        "quantity": "1",
        "unit_cost": "370",
        "currency": "MXN",
        "unit": "month",
        "billing_frequency": "monthly",
        "start_date": "2026-04-01",
        "record_type": "actual",
        "notes": "Initial version",
        "cost_key": "infrastructure.hetzner.server",
    }
    values.update(overrides)
    return CostCommand(**values)


def test_create_persists_cost_and_audit_timestamps(repository: CostRepository) -> None:
    created = repository.create_cost(command())

    assert repository.get_cost(created.id).name == "Managed server"
    assert created.created_at is not None
    assert created.updated_at is not None
    assert created.created_at == created.updated_at


def test_generated_cost_key_uses_formatted_id_and_descriptive_fields(repository: CostRepository) -> None:
    created = repository.create_cost(command(cost_key=None))

    assert created.cost_key == "0001-Managed server-Hetzner-Infrastructure"


def test_entered_currency_is_preserved_while_economic_value_is_normalized(repository: CostRepository) -> None:
    created = repository.create_cost(command(cost_key=None, unit_cost="6", currency="USD"))

    assert created.entered_unit_cost == Decimal("6")
    assert created.entered_currency == "USD"
    assert created.unit_cost == Decimal("108")
    assert created.currency == "MXN"
    assert created.entered_configured_amount == Decimal("6")


def test_initial_csv_seed_import_is_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    first_count = ensure_cost_seeded(BASE_DIR / "data" / "seed_costs.csv", factory)
    second_count = ensure_cost_seeded(BASE_DIR / "data" / "seed_costs.csv", factory)

    assert first_count > 0
    assert second_count == 0
    assert CostRepository(factory).count() == first_count


def test_metadata_update_preserves_created_at_and_advances_updated_at(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    updated = repository.update_cost_metadata(
        created.id,
        MetadataCommand("Managed server EU", "Hetzner", "Infrastructure", "Shared", "Renamed"),
        created.updated_at,
    )

    assert updated.created_at == created.created_at
    assert updated.updated_at > created.updated_at
    assert updated.name == "Managed server EU"
    assert updated.unit_cost == Decimal("370")
    assert updated.start_date == created.start_date


def test_metadata_update_can_correct_or_clear_lifecycle_dates(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    corrected = repository.update_cost_metadata(
        created.id,
        MetadataCommand(
            created.name,
            created.provider,
            created.category,
            created.service_line,
            created.notes,
            start_date="2026-05-01",
            end_date="2026-09-30",
        ),
        created.updated_at,
    )
    cleared = repository.update_cost_metadata(
        corrected.id,
        MetadataCommand(
            corrected.name,
            corrected.provider,
            corrected.category,
            corrected.service_line,
            corrected.notes,
            start_date="2026-05-01",
            end_date="",
        ),
        corrected.updated_at,
    )

    assert corrected.start_date == date(2026, 5, 1)
    assert corrected.end_date == date(2026, 9, 30)
    assert cleared.start_date == date(2026, 5, 1)
    assert cleared.end_date is None


def test_metadata_lifecycle_correction_rejects_invalid_date_order(repository: CostRepository) -> None:
    created = repository.create_cost(command())

    with pytest.raises(CostValidationError, match="End date"):
        repository.update_cost_metadata(
            created.id,
            MetadataCommand(
                created.name,
                created.provider,
                created.category,
                created.service_line,
                created.notes,
                start_date="2026-08-01",
                end_date="2026-07-31",
            ),
            created.updated_at,
        )

    assert repository.get_cost(created.id).start_date == date(2026, 4, 1)


def test_metadata_lifecycle_correction_rejects_overlap(repository: CostRepository) -> None:
    original = repository.create_cost(command(end_date="2026-06-30"))
    repository.create_cost(command(start_date="2026-07-01", unit_cost="450"))

    with pytest.raises(CostValidationError, match="overlap"):
        repository.update_cost_metadata(
            original.id,
            MetadataCommand(
                original.name,
                original.provider,
                original.category,
                original.service_line,
                original.notes,
                start_date=original.start_date,
                end_date="2026-07-31",
            ),
            original.updated_at,
        )

    assert repository.get_cost(original.id).end_date == date(2026, 6, 30)


def test_economic_change_creates_version_and_closes_previous(repository: CostRepository) -> None:
    original = repository.create_cost(command())
    replacement = repository.create_cost_version(
        original.id,
        {"unit_cost": "450"},
        date(2026, 7, 1),
        original.updated_at,
    )
    versions = sorted(repository.list_costs(), key=lambda item: item.start_date)

    assert len(versions) == 2
    assert versions[0].id == original.id
    assert versions[0].unit_cost == Decimal("370")
    assert versions[0].end_date == date(2026, 6, 30)
    assert replacement.id != original.id
    assert replacement.cost_key == original.cost_key
    assert replacement.unit_cost == Decimal("450")
    assert replacement.start_date == date(2026, 7, 1)


def test_overlapping_actual_version_is_rejected_and_rolled_back(repository: CostRepository) -> None:
    original = repository.create_cost(command(end_date="2026-06-30"))

    with pytest.raises(CostValidationError, match="overlap"):
        repository.create_cost(command(start_date="2026-06-01", unit_cost="450"))

    persisted = repository.list_costs()
    assert [item.id for item in persisted] == [original.id]
    assert persisted[0].end_date == date(2026, 6, 30)


def test_end_preserves_enabled_record_and_deactivation_never_deletes(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    ended = repository.end_cost(created.id, "2026-08-31", created.updated_at)
    deactivated = repository.deactivate_cost(ended.id, ended.updated_at)

    assert ended.enabled is True
    assert ended.end_date == date(2026, 8, 31)
    assert deactivated.enabled is False
    assert repository.get_cost(created.id).id == created.id
    assert not hasattr(repository, "delete_cost")


def test_reactivation_restores_ended_record_without_changing_dates(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    ended = repository.end_cost(created.id, "2026-08-31", created.updated_at)
    deactivated = repository.deactivate_cost(ended.id, ended.updated_at)

    reactivated = repository.reactivate_cost(deactivated.id, deactivated.updated_at)

    assert reactivated.enabled is True
    assert reactivated.end_date == date(2026, 8, 31)
    assert reactivated.created_at == created.created_at
    assert reactivated.updated_at > deactivated.updated_at


def test_reactivation_rejects_overlapping_actual_version(repository: CostRepository) -> None:
    original = repository.create_cost(command())
    deactivated = repository.deactivate_cost(original.id, original.updated_at)
    repository.create_cost(command(start_date="2026-07-01", unit_cost="450"))

    with pytest.raises(CostValidationError, match="overlap"):
        repository.reactivate_cost(deactivated.id, deactivated.updated_at)

    assert repository.get_cost(deactivated.id).enabled is False


def test_stale_updated_at_rejects_silent_overwrite(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    stale = created.updated_at
    repository.update_cost_metadata(
        created.id,
        MetadataCommand(created.name, created.provider, created.category, created.service_line, "First writer"),
        stale,
    )

    with pytest.raises(CostConcurrencyError, match="another user"):
        repository.end_cost(created.id, "2026-12-31", stale)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"quantity": "not-a-decimal"}, "decimal"),
        ({"unit_cost": "-1"}, "non-negative"),
        ({"currency": "EUR"}, "currency"),
        ({"cost_type": "unknown"}, "cost type"),
        ({"start_date": "31/07/2026"}, "ISO date"),
    ],
)
def test_invalid_boundary_values_are_rejected(repository: CostRepository, overrides: dict, message: str) -> None:
    with pytest.raises(CostValidationError, match=message):
        repository.create_cost(command(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"cost_type": "variable", "billing_frequency": "monthly"},
        {"cost_type": "fixed", "billing_frequency": "usage"},
    ],
)
def test_inconsistent_cost_type_and_frequency_are_rejected(
    repository: CostRepository, overrides: dict
) -> None:
    with pytest.raises(CostValidationError, match="frequency|Frequency"):
        repository.create_cost(command(**overrides))


def test_expected_timestamp_accepts_utc_iso_string(repository: CostRepository) -> None:
    created = repository.create_cost(command())
    expected = created.updated_at.astimezone(UTC).isoformat()

    ended = repository.end_cost(created.id, "2026-12-31", expected)

    assert ended.updated_at > created.updated_at
