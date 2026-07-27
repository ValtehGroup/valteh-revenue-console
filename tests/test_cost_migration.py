from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _upgrade(database_path: Path) -> sa.Engine:
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return sa.create_engine(database_url)


def test_migration_creates_cost_schema_in_empty_database(tmp_path: Path) -> None:
    engine = _upgrade(tmp_path / "new.db")
    inspector = sa.inspect(engine)

    assert "cost_items" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("cost_items")}
    assert {"created_at", "updated_at", "entered_unit_cost", "entered_currency"} <= columns
    assert inspector.get_pk_constraint("cost_items")["constrained_columns"] == ["id"]
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("cost_items")}
    assert "ck_cost_items_type_frequency" in checks


def test_migration_upgrades_prior_cost_schema_and_preserves_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "prior.db"
    engine = sa.create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(sa.text("""
                CREATE TABLE cost_items (
                    id INTEGER PRIMARY KEY,
                    cost_key VARCHAR(120) NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    provider VARCHAR(120),
                    category VARCHAR(80) NOT NULL,
                    service_line VARCHAR(80),
                    cost_type VARCHAR(40) NOT NULL,
                    charge_basis VARCHAR(80) NOT NULL,
                    quantity NUMERIC(18, 6),
                    unit_cost NUMERIC(12, 6),
                    unit VARCHAR(80) NOT NULL,
                    billing_frequency VARCHAR(40) NOT NULL,
                    start_date DATE,
                    end_date DATE,
                    currency VARCHAR(3),
                    record_type VARCHAR(40),
                    enabled BOOLEAN,
                    notes TEXT
                )
                """))
        connection.execute(sa.text("""
                INSERT INTO cost_items (
                    id, cost_key, name, category, cost_type, charge_basis, quantity, unit_cost,
                    unit, billing_frequency, start_date, currency, record_type, enabled
                ) VALUES (7, 'legacy.one-time', 'Legacy purchase', 'Software', 'one_time', 'flat', 1, 25,
                          'payment', 'once', '2026-05-15', 'MXN', 'actual', 1)
                """))
        connection.execute(sa.text("""
                INSERT INTO cost_items (
                    id, cost_key, name, provider, category, cost_type, charge_basis, quantity, unit_cost,
                    unit, billing_frequency, start_date, currency, record_type, enabled
                ) VALUES (3, 'software.microsoft365.team', 'Microsoft 365 team subscription', 'Microsoft',
                          'Software', 'fixed', 'per_user', 4, 108, 'user-month', 'monthly', '2026-05-01',
                          'MXN', 'actual', 1)
                """))
        connection.execute(sa.text("""
                INSERT INTO cost_items (
                    id, cost_key, name, category, cost_type, charge_basis, quantity, unit_cost,
                    unit, billing_frequency, currency, record_type, enabled
                ) VALUES (1, 'legacy.cost', 'Legacy', 'Admin', 'fixed', 'flat', 1, 10,
                          'month', 'monthly', 'MXN', 'actual', 1)
                """))

    migrated_engine = _upgrade(database_path)
    columns = {column["name"]: column for column in sa.inspect(migrated_engine).get_columns("cost_items")}
    with migrated_engine.connect() as connection:
        row = connection.execute(sa.text("SELECT id, created_at, updated_at FROM cost_items WHERE id = 1")).one()
        microsoft = connection.execute(
            sa.text("SELECT entered_unit_cost, entered_currency FROM cost_items WHERE id = 3")
        ).one()
        one_time = connection.execute(
            sa.text("SELECT cost_type, billing_frequency FROM cost_items WHERE id = 7")
        ).one()

    assert columns["created_at"]["nullable"] is False
    assert columns["updated_at"]["nullable"] is False
    assert columns["entered_unit_cost"]["nullable"] is False
    assert columns["entered_currency"]["nullable"] is False
    assert row.id == 1
    assert row.created_at is not None
    assert row.updated_at is not None
    assert microsoft.entered_unit_cost == 6
    assert microsoft.entered_currency == "USD"
    assert one_time.cost_type == "fixed"
    assert one_time.billing_frequency == "once"
