from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.data.database import SessionLocal, init_db, migrate_db
from app.data.schemas import CostItemORM


def seed_database() -> None:
    """Initialize the schema and import reference costs exactly once."""
    init_db()
    migrate_db()
    ensure_cost_seeded(get_settings().seed_data_dir / "seed_costs.csv")


def ensure_cost_seeded(csv_path: Path, session_factory=SessionLocal) -> int:
    """Import the validated CSV only while the runtime cost catalog is empty."""

    from app.data.repositories import SeedRepository

    with session_factory.begin() as session:
        if session.scalar(select(func.count()).select_from(CostItemORM)):
            return 0
        items = SeedRepository(data_dir=str(csv_path.parent)).seed_cost_items()
        now = datetime.now(UTC)
        session.add_all(
            [
                CostItemORM(
                    **item.model_dump(exclude={"created_at", "updated_at"}),
                    created_at=now,
                    updated_at=now,
                )
                for item in items
            ]
        )
        return len(items)
