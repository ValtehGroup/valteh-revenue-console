import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

from app.config import get_settings
from app.data.database import SessionLocal, migrate_db
from app.data.schemas import ClientORM, ClientSubscriptionORM, CostItemORM, PricingPlanORM, UsageEventORM
from app.domain.models import ClientSubscription, PricingPlan, UsageEvent


def seed_database() -> None:
    """Initialize the schema and import runtime reference data exactly once."""
    migrate_db()
    seed_dir = get_settings().seed_data_dir
    ensure_client_seeded(
        seed_dir / "seed_clients.csv",
        seed_dir / "seed_pricing_plans.csv",
        seed_dir / "seed_client_subscriptions.csv",
    )
    ensure_usage_seeded(seed_dir / "seed_usage.csv")
    ensure_cost_seeded(seed_dir / "seed_costs.csv")


def ensure_client_seeded(
    clients_path: Path,
    pricing_plans_path: Path,
    subscriptions_path: Path,
    session_factory=SessionLocal,
) -> int:
    """Import clients and their minimal commercial references only into empty tables."""

    inserted = 0
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        if not session.scalar(select(func.count()).select_from(PricingPlanORM)):
            plan_records = pd.read_csv(pricing_plans_path, keep_default_na=False).to_dict("records")
            for record in plan_records:
                dedicated_client_id = str(record.get("dedicated_client_id", "")).strip()
                record["dedicated_client_id"] = int(dedicated_client_id) if dedicated_client_id else None
            session.add_all([PricingPlanORM(**PricingPlan(**record).model_dump()) for record in plan_records])

        if not session.scalar(select(func.count()).select_from(ClientORM)):
            frame = pd.read_csv(clients_path, keep_default_na=False)
            for record in frame.to_dict("records"):
                client_id = int(record["id"])
                session.add(
                    ClientORM(
                        id=client_id,
                        client_code=str(record.get("client_code") or f"client_{client_id:04d}").strip(),
                        name=str(record["name"]).strip(),
                        client_type=str(record["client_type"]).strip(),
                        status=str(record["status"]).strip(),
                        start_date=_seed_date(record["start_date"], required=True),
                        end_date=_seed_date(record.get("end_date")),
                        notes=str(record.get("notes", "")).strip() or None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                inserted += 1
            session.flush()

        if not session.scalar(select(func.count()).select_from(ClientSubscriptionORM)):
            frame = pd.read_csv(subscriptions_path, keep_default_na=False)
            for record in frame.to_dict("records"):
                values = {
                    **record,
                    "id": int(record["id"]),
                    "client_id": int(record["client_id"]),
                    "pricing_plan_id": int(record["pricing_plan_id"]),
                    "start_date": _seed_date(record["start_date"], required=True),
                    "end_date": _seed_date(record.get("end_date")),
                    "notes": str(record.get("notes", "")).strip() or None,
                }
                session.add(ClientSubscriptionORM(**ClientSubscription(**values).model_dump()))
    return inserted


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


def ensure_usage_seeded(csv_path: Path, session_factory=SessionLocal) -> int:
    """Insert missing historical seed usage without replacing imported events."""

    inserted = 0
    frame = pd.read_csv(csv_path, keep_default_na=False)
    with session_factory.begin() as session:
        existing_ids = set(session.scalars(select(UsageEventORM.id)))
        existing_references = set(
            session.execute(
                select(UsageEventORM.source_system, UsageEventORM.external_reference_id).where(
                    UsageEventORM.external_reference_id.is_not(None)
                )
            ).all()
        )
        for record in frame.to_dict("records"):
            reference = str(record.get("external_reference_id", "")).strip() or None
            source_system = str(record["source_system"]).strip()
            if reference is not None and (source_system, reference) in existing_references:
                continue
            metadata = str(record.get("metadata_json", "")).strip()
            event = UsageEvent(
                id=int(record["id"]),
                client_id=int(record["client_id"]),
                service_code=str(record["service_code"]).strip(),
                event_type=str(record["event_type"]).strip(),
                quantity=record["quantity"],
                unit=str(record["unit"]).strip(),
                event_timestamp=pd.to_datetime(record["event_timestamp"]).to_pydatetime(),
                source_system=source_system,
                external_reference_id=reference,
                metadata_json=json.loads(metadata) if metadata else {},
            )
            values = event.model_dump()
            values["metadata_json"] = json.dumps(values["metadata_json"], separators=(",", ":"), sort_keys=True)
            if event.id in existing_ids:
                values.pop("id")
            row = UsageEventORM(**values)
            session.add(row)
            session.flush()
            existing_ids.add(row.id)
            if reference is not None:
                existing_references.add((source_system, reference))
            inserted += 1
    return inserted


def _seed_date(value, *, required: bool = False):
    if value in (None, ""):
        if required:
            raise ValueError("A required seed date is missing.")
        return None
    return pd.to_datetime(value, dayfirst=True).date()
