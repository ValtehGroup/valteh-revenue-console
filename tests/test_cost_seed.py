from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.data.repositories import (
    OPTIONAL_COST_COLUMNS,
    REQUIRED_COST_COLUMNS,
    SeedRepository,
    _normalize_cost_record,
    _parse_bool,
    _validate_duplicate_cost_ids,
)
from app.data.seed_data import seed_database
from app.domain.cost_engine import calculate_fixed_costs
from app.domain.fx_rates import USD_MXN_FIX_SERIES_ID, DatedFxRateBook, FxRateObservation


def _seed_record(**overrides) -> pd.Series:
    values = {
        "id": "1",
        "cost_key": "software.microsoft365.team",
        "name": "Microsoft 365 team subscription",
        "provider": "Microsoft",
        "category": "Software",
        "service_line": "Shared",
        "cost_type": "fixed",
        "charge_basis": "per_user",
        "quantity": "2",
        "unit_cost": "200",
        "unit": "user-month",
        "billing_frequency": "monthly",
        "start_date": "2026-05-01",
        "end_date": "2026-06-30",
        "currency": "MXN",
        "record_type": "actual",
        "enabled": "TRUE",
        "notes": "Original rate",
    }
    values.update(overrides)
    return pd.Series({column: values[column] for column in REQUIRED_COST_COLUMNS | OPTIONAL_COST_COLUMNS})


def test_loads_new_cost_seed_schema() -> None:
    items = SeedRepository().seed_cost_items()

    assert items
    assert len({item.id for item in items}) == len(items)
    microsoft_versions = [item for item in items if item.cost_key == "software.microsoft365.team"]
    assert [item.start_date for item in microsoft_versions] == [date(2026, 5, 1), date(2026, 7, 1)]
    assert microsoft_versions[0].quantity == Decimal("4")
    assert microsoft_versions[0].unit_cost == Decimal("108")
    assert microsoft_versions[1].unit_cost == Decimal("144")
    assert all(item.currency == "MXN" for item in microsoft_versions)


def test_boolean_parsing_accepts_csv_true_false_values() -> None:
    assert _parse_bool("TRUE", row_number=2, column="enabled") is True
    assert _parse_bool("FALSE", row_number=2, column="enabled") is False
    assert _parse_bool("ON", row_number=2, column="enabled") is True
    assert _parse_bool("OFF", row_number=2, column="enabled") is False


def test_boolean_parsing_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="must be a Boolean"):
        _parse_bool("maybe", row_number=2, column="enabled")


def test_date_parsing_accepts_iso_dates() -> None:
    record = _normalize_cost_record(_seed_record(start_date="2026-07-01", end_date=""), row_number=2)

    assert record["start_date"] == date(2026, 7, 1)
    assert record["end_date"] is None


def test_date_parsing_accepts_day_first_dates() -> None:
    record = _normalize_cost_record(_seed_record(start_date="01/07/2026", end_date="31/07/2026"), row_number=2)

    assert record["start_date"] == date(2026, 7, 1)
    assert record["end_date"] == date(2026, 7, 31)


def test_date_parsing_rejects_invalid_dates() -> None:
    with pytest.raises(ValueError, match="valid date"):
        _normalize_cost_record(_seed_record(start_date="not-a-date"), row_number=2)


def test_non_numeric_quantity_is_rejected() -> None:
    with pytest.raises(ValueError, match="quantity.*numeric"):
        _normalize_cost_record(_seed_record(quantity="many"), row_number=2)


def test_unsupported_charge_basis_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported value"):
        _normalize_cost_record(_seed_record(charge_basis="per-seat"), row_number=2)


def test_negative_unit_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="unit_cost.*cannot be negative"):
        _normalize_cost_record(_seed_record(unit_cost="-1"), row_number=2)


def test_usd_unit_cost_is_converted_to_mxn() -> None:
    record = _normalize_cost_record(_seed_record(unit_cost="6", currency="USD"), row_number=2)

    assert record["unit_cost"] == Decimal("108")
    assert record["currency"] == "MXN"
    assert record["entered_unit_cost"] == Decimal("6")
    assert record["entered_currency"] == "USD"


def test_unsupported_currency_is_rejected() -> None:
    with pytest.raises(ValueError, match="currency.*unsupported value"):
        _normalize_cost_record(_seed_record(currency="EUR"), row_number=2)


def test_duplicate_record_ids_are_rejected() -> None:
    records = [
        _normalize_cost_record(_seed_record(id="1"), row_number=2),
        _normalize_cost_record(_seed_record(id="1", cost_key="software.other"), row_number=3),
    ]

    with pytest.raises(ValueError, match="duplicate cost record ids"):
        _validate_duplicate_cost_ids(records)


def test_blank_id_defaults_to_csv_record_position() -> None:
    record = _normalize_cost_record(_seed_record(id=""), row_number=7)

    assert record["id"] == 6


def test_blank_cost_key_is_derived_from_stable_record_fields() -> None:
    record = _normalize_cost_record(_seed_record(cost_key=""), row_number=2)

    assert record["cost_key"] == "software.microsoft.microsoft.365.team.subscription"


def test_microsoft_seed_history_uses_dated_month_end_fx_rates() -> None:
    microsoft_versions = [
        item for item in SeedRepository().seed_cost_items() if item.cost_key == "software.microsoft365.team"
    ]
    rates = DatedFxRateBook(
        [
            FxRateObservation(USD_MXN_FIX_SERIES_ID, date(2026, 5, 29), Decimal("18")),
            FxRateObservation(USD_MXN_FIX_SERIES_ID, date(2026, 6, 30), Decimal("19")),
            FxRateObservation(USD_MXN_FIX_SERIES_ID, date(2026, 7, 31), Decimal("20")),
        ]
    )

    assert calculate_fixed_costs(microsoft_versions, date(2026, 5, 1), rates) == Decimal("432")
    assert calculate_fixed_costs(microsoft_versions, date(2026, 6, 1), rates) == Decimal("456")
    assert calculate_fixed_costs(microsoft_versions, date(2026, 7, 1), rates) == Decimal("640")


def test_dashboard_service_functions_use_monthly_cost_totals() -> None:
    repo = SeedRepository()
    costs = repo.monthly_cost_amounts("2026-06")
    summary = repo.monthly_summary("2026-06")
    expected_fixed = sum(
        (cost.amount for cost in costs if cost.cost_type == "fixed"),
        Decimal("0"),
    )
    expected_variable = sum(
        (cost.amount for cost in costs if cost.cost_type == "variable"),
        Decimal("0"),
    )

    assert summary["fixed_cost"] == expected_fixed
    assert summary["variable_cost"] == expected_variable
    assert sum(repo.cost_by_service("2026-06").values(), Decimal("0")) == expected_fixed + expected_variable
    assert sum(repo.cost_by_category("2026-06").values(), Decimal("0")) == expected_fixed + expected_variable
    assert sum(repo.cost_by_provider("2026-06").values(), Decimal("0")) == expected_fixed + expected_variable


def test_available_months_run_from_first_cost_month_to_current_month(monkeypatch) -> None:
    monkeypatch.setattr("app.data.repositories.current_month_key", lambda: "2026-07")

    assert SeedRepository().available_months() == ["2026-04", "2026-05", "2026-06", "2026-07"]


def test_seed_database_runs_versioned_migrations_before_idempotent_seeding(monkeypatch) -> None:
    calls = []

    def fake_migrate_db() -> None:
        calls.append("migrate")

    monkeypatch.setattr("app.data.seed_data.migrate_db", fake_migrate_db)
    monkeypatch.setattr("app.data.seed_data.ensure_client_seeded", lambda *_args: 0)
    monkeypatch.setattr("app.data.seed_data.ensure_usage_seeded", lambda *_args: 0)
    monkeypatch.setattr("app.data.seed_data.ensure_cost_seeded", lambda *_args: 0)

    seed_database()
    seed_database()

    assert calls == ["migrate", "migrate"]
