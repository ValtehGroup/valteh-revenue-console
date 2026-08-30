from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

REVISION = "20260827_08"
CONSOLE_HEAD_REVISION = "20260830_13"
MIGRATION_FILE = "20260827_08_anthropic_history.py"


def _upgrade(repo_root: Path, database_url: str) -> None:
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def test_operational_event_migration_creates_provenance_and_status_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'events.db').as_posix()}"
    _upgrade(Path(__file__).resolve().parents[1], database_url)
    inspector = sa.inspect(sa.create_engine(database_url))

    assert {
        "event_classifications",
        "event_import_cursors",
        "imported_operational_events",
        "usage_events",
    } <= set(inspector.get_table_names())
    assert "imported_event_id" in {column["name"] for column in inspector.get_columns("usage_events")}
    assert {"classification_attempts", "classified_at"} <= {
        column["name"] for column in inspector.get_columns("imported_operational_events")
    }
    assert "uq_usage_events_imported_event_id" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("usage_events")
    }


def test_console_and_api_accept_the_same_alembic_revision_chain(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sibling_name = "valteh-revenue-api" if repo_root.name == "valteh-revenue-console" else "valteh-revenue-console"
    sibling_root = repo_root.parent / sibling_name
    if not (sibling_root / "alembic.ini").exists():
        pytest.skip("Sibling revenue repository is not available in this checkout.")

    own_migration = repo_root / "migrations" / "versions" / MIGRATION_FILE
    sibling_migration = sibling_root / "migrations" / "versions" / MIGRATION_FILE
    assert own_migration.read_bytes() == sibling_migration.read_bytes()

    database_url = f"sqlite:///{(tmp_path / 'shared.db').as_posix()}"
    _upgrade(repo_root, database_url)
    _upgrade(sibling_root, database_url)
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == CONSOLE_HEAD_REVISION


def test_anthropic_history_migration_creates_unique_provider_fact_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'anthropic-history.db').as_posix()}"
    _upgrade(Path(__file__).resolve().parents[1], database_url)
    inspector = sa.inspect(sa.create_engine(database_url))

    assert {
        "anthropic_api_keys",
        "anthropic_api_key_assignments",
        "anthropic_cost_daily",
        "anthropic_sync_runs",
        "anthropic_sync_watermarks",
        "anthropic_usage_daily",
        "anthropic_workspaces",
    } <= set(inspector.get_table_names())
    assert "uq_anthropic_usage_daily_identity" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("anthropic_usage_daily")
    }
    assert "uq_anthropic_cost_daily_identity" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("anthropic_cost_daily")
    }
