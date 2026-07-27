from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import select

from app.config import BASE_DIR, get_settings
from app.domain.cost_engine import calculate_variable_cost, is_cost_effective, monthly_cost_amounts
from app.domain.models import (
    Client,
    ClientProfitability,
    ClientSubscription,
    CostItem,
    PricingPlan,
    RevenueEvent,
    Service,
    UsageEvent,
)
from app.domain.revenue_engine import (
    calculate_client_revenue,
    calculate_subscription_revenue,
    calculate_usage_revenue,
)
from app.domain.unit_economics import calculate_gross_margin, calculate_gross_margin_percentage
from app.utils.currency import BASE_CURRENCY, STATIC_EXCHANGE_RATES_TO_MXN, convert_to_mxn
from app.utils.dates import current_month_key, month_key, month_range

REQUIRED_COST_COLUMNS = {
    "name",
    "provider",
    "category",
    "service_line",
    "cost_type",
    "charge_basis",
    "quantity",
    "unit_cost",
    "unit",
    "billing_frequency",
    "start_date",
    "end_date",
    "currency",
    "record_type",
    "enabled",
    "notes",
}
OPTIONAL_COST_COLUMNS = {"id", "cost_key"}

SUPPORTED_COST_TYPES = {"fixed", "variable"}
SUPPORTED_CHARGE_BASES = {"flat", "per_user", "usage"}
SUPPORTED_BILLING_FREQUENCIES = {"monthly", "annual", "usage", "once"}
SUPPORTED_RECORD_TYPES = {"actual", "budget", "estimate"}
SUPPORTED_COST_CURRENCIES = set(STATIC_EXCHANGE_RATES_TO_MXN)


@dataclass
class SeedRepository:
    """CSV-backed repository used by the first app version."""

    data_dir: str | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.data_path = settings.seed_data_dir if self.data_dir is None else BASE_DIR / self.data_dir

    def clients(self) -> list[Client]:
        from app.data.client_repository import ClientRepository

        return sorted(ClientRepository().list_clients(), key=lambda client: client.id)

    def services(self) -> list[Service]:
        return [
            Service(
                id=1,
                code="saremi",
                name="SAREMI",
                description="Document validation and AI review service.",
                service_line="SAREMI",
            ),
            Service(
                id=2,
                code="graphos",
                name="Graphos",
                description="Ownership and counterparty graph analytics.",
                service_line="Graphos",
            ),
            Service(
                id=3,
                code="blockchain",
                name="Blockchain / BaaS",
                description="Registry events, certificates, and chaincode execution.",
                service_line="Blockchain / BaaS",
            ),
            Service(
                id=4,
                code="sigen",
                name="SIGEN / Notarial Platform",
                description="Client-facing notarial platform.",
                service_line="SIGEN",
            ),
        ]

    def pricing_plans(self) -> list[PricingPlan]:
        from app.data.database import SessionLocal
        from app.data.schemas import PricingPlanORM

        with SessionLocal() as session:
            rows = session.scalars(select(PricingPlanORM).order_by(PricingPlanORM.id)).all()
            return [
                PricingPlan.model_validate(
                    {column.name: getattr(row, column.name) for column in PricingPlanORM.__table__.columns}
                )
                for row in rows
            ]

    def subscriptions(self) -> list[ClientSubscription]:
        from app.data.database import SessionLocal
        from app.data.schemas import ClientSubscriptionORM

        with SessionLocal() as session:
            rows = session.scalars(select(ClientSubscriptionORM).order_by(ClientSubscriptionORM.id)).all()
            return [
                ClientSubscription.model_validate(
                    {column.name: getattr(row, column.name) for column in ClientSubscriptionORM.__table__.columns}
                )
                for row in rows
            ]

    def usage_events(self) -> list[UsageEvent]:
        df = pd.read_csv(self.data_path / "seed_usage.csv", parse_dates=["event_timestamp"])
        records = []
        for record in df.to_dict("records"):
            metadata = record.get("metadata_json")
            record["metadata_json"] = json.loads(metadata) if isinstance(metadata, str) and metadata else {}
            records.append(record)
        return [UsageEvent(**record) for record in records]

    def cost_items(self) -> list[CostItem]:
        from app.data.cost_repository import CostRepository
        from app.data.seed_data import ensure_cost_seeded

        ensure_cost_seeded(self.data_path / "seed_costs.csv")
        return sorted(CostRepository().list_costs(), key=lambda item: item.id)

    def seed_cost_items(self) -> list[CostItem]:
        """Parse and validate the reference CSV without touching runtime persistence."""

        df = pd.read_csv(self.data_path / "seed_costs.csv", dtype="string", keep_default_na=False)
        _validate_required_cost_columns(df)
        for column in OPTIONAL_COST_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        normalized_records = [_normalize_cost_record(record, row_number=index + 2) for index, record in df.iterrows()]
        _validate_duplicate_cost_ids(normalized_records)
        items = [CostItem(**record) for record in normalized_records]
        _validate_cost_versions(items)
        return items

    def revenue_events(self) -> list[RevenueEvent]:
        events: list[RevenueEvent] = []
        event_id = 1
        for month in self.available_months():
            for client in self.active_clients(month):
                subscription = self.active_subscription_for_client_month(client.id, month)
                plan = self.active_plan_for_client_month(client.id, month)
                if plan is None or subscription is None:
                    continue
                usage = self.usage_for_client_month(client.id, month)
                period_month = pd.Timestamp(f"{month}-01").date()
                subscription_amount = calculate_subscription_revenue(plan, subscription, period_month)
                usage_amount = calculate_usage_revenue(usage, plan)
                has_usage_activity = bool(usage)
                for revenue_type, service_code, amount, description in [
                    (
                        "subscription",
                        "sigen",
                        subscription_amount,
                        f"{plan.name} fixed subscription revenue for {month}",
                    ),
                    (
                        "usage",
                        "usage",
                        usage_amount,
                        f"{plan.name} billable usage revenue for {month}",
                    ),
                ]:
                    if amount == 0 and not (revenue_type == "usage" and has_usage_activity):
                        continue
                    events.append(
                        RevenueEvent(
                            id=event_id,
                            client_id=client.id,
                            service_code=service_code,
                            revenue_type=revenue_type,
                            amount=amount,
                            currency="MXN",
                            event_timestamp=pd.Timestamp(f"{month}-28").to_pydatetime(),
                            description=description,
                        )
                    )
                    event_id += 1
        return events

    def active_clients(self, month: str) -> list[Client]:
        month_start = pd.Timestamp(f"{month}-01").date()
        return [
            client
            for client in self.clients()
            if client.start_date <= month_start
            and (
                (client.end_date is not None and client.end_date >= month_start)
                or (client.end_date is None and client.status == "active")
            )
        ]

    def active_plan_for_client(self, client_id: int) -> PricingPlan | None:
        return self.active_plan_for_client_month(client_id, self.available_months()[-1])

    def active_plan_for_client_month(self, client_id: int, month: str) -> PricingPlan | None:
        subscription = self.active_subscription_for_client_month(client_id, month)
        if subscription is None:
            return None
        return next((plan for plan in self.pricing_plans() if plan.id == subscription.pricing_plan_id), None)

    def active_subscription_for_client_month(self, client_id: int, month: str) -> ClientSubscription | None:
        if client_id not in {client.id for client in self.active_clients(month)}:
            return None
        month_start = pd.Timestamp(f"{month}-01").date()
        return next(
            (
                sub
                for sub in self.subscriptions()
                if sub.client_id == client_id
                and (sub.status == "active" or sub.end_date is not None)
                and sub.start_date <= month_start
                and (sub.end_date is None or sub.end_date >= month_start)
            ),
            None,
        )

    def subscription_for_client_month(self, client_id: int, month: str) -> ClientSubscription | None:
        """Return the subscription effective in a historical month, regardless of current client status."""

        month_start = pd.Timestamp(f"{month}-01").date()
        return next(
            (
                subscription
                for subscription in self.subscriptions()
                if subscription.client_id == client_id
                and subscription.start_date <= month_start
                and (subscription.end_date is None or subscription.end_date >= month_start)
            ),
            None,
        )

    def available_months(self) -> list[str]:
        cost_months = {month_key(item.start_date) for item in self.cost_items() if item.start_date is not None}
        usage_months = {event.event_timestamp.strftime("%Y-%m") for event in self.usage_events()}
        known_months = cost_months | usage_months
        if not known_months:
            return [current_month_key()]
        return month_range(min(known_months), max(current_month_key(), *usage_months))

    def usage_for_month(self, month: str) -> list[UsageEvent]:
        active_client_ids = {client.id for client in self.active_clients(month)}
        return [
            event
            for event in self.usage_events()
            if event.client_id in active_client_ids and event.event_timestamp.strftime("%Y-%m") == month
        ]

    def usage_for_client_month(self, client_id: int, month: str) -> list[UsageEvent]:
        return [event for event in self.usage_for_month(month) if event.client_id == client_id]

    def usage_history_for_client_month(self, client_id: int, month: str) -> list[UsageEvent]:
        """Return recorded usage without applying the current active-client filter."""

        return [
            event
            for event in self.usage_events()
            if event.client_id == client_id and event.event_timestamp.strftime("%Y-%m") == month
        ]

    def cost_rates(self, as_of: date | None = None) -> dict[str, Decimal]:
        as_of = as_of or date.today()
        rates: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in self.cost_items():
            if item.cost_type == "variable" and is_cost_effective(item, as_of):
                rates[item.unit] += Decimal(str(item.unit_cost))
        return dict(rates)

    def monthly_cost_amounts(self, month: str):
        period_month = pd.Timestamp(f"{month}-01").date()
        return monthly_cost_amounts(self.cost_items(), period_month, self.usage_for_month(month))

    def client_profitability(self, client_id: int, month: str) -> ClientProfitability:
        usage = self.usage_for_client_month(client_id, month)
        subscription = self.active_subscription_for_client_month(client_id, month)
        if subscription is None:
            revenue = Decimal("0")
        else:
            plan = next(plan for plan in self.pricing_plans() if plan.id == subscription.pricing_plan_id)
            revenue = calculate_client_revenue(usage, plan, subscription, pd.Timestamp(f"{month}-01").date())
        variable_cost = calculate_variable_cost(usage, self.cost_items())
        return ClientProfitability(
            client_id=client_id,
            revenue=revenue,
            variable_cost=variable_cost,
            gross_margin=calculate_gross_margin(revenue, variable_cost),
            gross_margin_percentage=calculate_gross_margin_percentage(revenue, variable_cost),
        )

    def client_revenue_split(self, client_id: int, month: str) -> dict[str, Decimal]:
        subscription = self.active_subscription_for_client_month(client_id, month)
        if subscription is None:
            return {"subscription": Decimal("0"), "usage": Decimal("0"), "total": Decimal("0")}
        plan = next(plan for plan in self.pricing_plans() if plan.id == subscription.pricing_plan_id)
        usage = self.usage_for_client_month(client_id, month)
        period_month = pd.Timestamp(f"{month}-01").date()
        subscription_revenue = calculate_subscription_revenue(plan, subscription, period_month)
        usage_revenue = calculate_usage_revenue(usage, plan)
        return {
            "subscription": subscription_revenue,
            "usage": usage_revenue,
            "total": subscription_revenue + usage_revenue,
        }

    def monthly_revenue_split(self, month: str) -> dict[str, Decimal]:
        split = {"subscription": Decimal("0"), "usage": Decimal("0"), "total": Decimal("0")}
        for client in self.active_clients(month):
            client_split = self.client_revenue_split(client.id, month)
            split["subscription"] += client_split["subscription"]
            split["usage"] += client_split["usage"]
            split["total"] += client_split["total"]
        return split

    def monthly_summary(self, month: str) -> dict[str, Decimal]:
        revenue = sum(
            (self.client_profitability(client.id, month).revenue for client in self.active_clients(month)),
            Decimal("0"),
        )
        cost_amounts = self.monthly_cost_amounts(month)
        variable_cost = sum(
            (cost.amount for cost in cost_amounts if cost.cost_type == "variable"),
            Decimal("0"),
        )
        fixed_cost = sum(
            (cost.amount for cost in cost_amounts if cost.cost_type == "fixed"),
            Decimal("0"),
        )
        gross_margin = calculate_gross_margin(revenue, variable_cost)
        operating_margin = gross_margin - fixed_cost
        return {
            "revenue": revenue,
            "variable_cost": variable_cost,
            "fixed_cost": fixed_cost,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "burn_rate": abs(min(operating_margin, Decimal("0"))),
        }

    def revenue_by_service(self, month: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for client in self.active_clients(month):
            plan = self.active_plan_for_client_month(client.id, month)
            subscription = self.active_subscription_for_client_month(client.id, month)
            if plan is None or subscription is None:
                continue
            totals["SIGEN"] += calculate_subscription_revenue(plan, subscription, pd.Timestamp(f"{month}-01").date())
        for client in self.active_clients(month):
            plan = self.active_plan_for_client_month(client.id, month)
            if plan is None:
                continue
            for event in self.usage_for_client_month(client.id, month):
                if event.event_type.startswith("saremi"):
                    totals["SAREMI"] += _event_revenue(event.event_type, event.quantity, plan)
                elif event.event_type.startswith("graphos"):
                    totals["Graphos"] += _event_revenue(event.event_type, event.quantity, plan)
                elif event.event_type.startswith("blockchain"):
                    totals["Blockchain / BaaS"] += _event_revenue(event.event_type, event.quantity, plan)
        return dict(totals)

    def cost_by_service(self, month: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for cost in self.monthly_cost_amounts(month):
            totals[cost.service_line] += cost.amount
        return dict(totals)

    def cost_by_provider(self, month: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for cost in self.monthly_cost_amounts(month):
            totals[cost.provider or "Unassigned"] += cost.amount
        return dict(totals)

    def cost_by_category(self, month: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for cost in self.monthly_cost_amounts(month):
            totals[cost.category] += cost.amount
        return dict(totals)

    def cost_history(self) -> list[dict[str, Decimal | str]]:
        rows = []
        for month in self.available_months():
            amounts = self.monthly_cost_amounts(month)
            rows.append(
                {
                    "month": month,
                    "fixed": sum(
                        (
                            cost.amount
                            for cost in amounts
                            if cost.cost_type == "fixed" and cost.billing_frequency != "once"
                        ),
                        Decimal("0"),
                    ),
                    "variable": sum((cost.amount for cost in amounts if cost.cost_type == "variable"), Decimal("0")),
                    "one_time": sum(
                        (cost.amount for cost in amounts if cost.billing_frequency == "once"), Decimal("0")
                    ),
                    "total": sum((cost.amount for cost in amounts), Decimal("0")),
                }
            )
        return rows

    def cost_versions(self, cost_key: str) -> list[CostItem]:
        return sorted(
            [item for item in self.cost_items() if item.cost_key == cost_key],
            key=lambda item: (item.start_date or date.min, item.id),
        )


def _validate_required_cost_columns(df: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_COST_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(f"seed_costs.csv is missing required columns: {', '.join(missing)}")


def _validate_duplicate_cost_ids(records: list[dict]) -> None:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for record in records:
        record_id = record["id"]
        if record_id in seen:
            duplicates.add(record_id)
        seen.add(record_id)
    if duplicates:
        duplicate_list = ", ".join(str(record_id) for record_id in sorted(duplicates))
        raise ValueError(f"seed_costs.csv has duplicate cost record ids: {duplicate_list}")


def _normalize_cost_record(record: pd.Series, *, row_number: int) -> dict:
    normalized = {key: _blank_to_none(record[key]) for key in REQUIRED_COST_COLUMNS | OPTIONAL_COST_COLUMNS}
    normalized["id"] = _parse_optional_positive_int(
        normalized["id"],
        default=row_number - 1,
        row_number=row_number,
        column="id",
    )
    normalized["name"] = _required_text(normalized["name"], row_number=row_number, column="name")
    normalized["category"] = _required_text(normalized["category"], row_number=row_number, column="category")
    normalized["unit"] = _required_text(normalized["unit"], row_number=row_number, column="unit")
    normalized["cost_type"] = _parse_supported_value(
        normalized["cost_type"],
        SUPPORTED_COST_TYPES,
        row_number=row_number,
        column="cost_type",
    )
    normalized["charge_basis"] = _parse_supported_value(
        normalized["charge_basis"],
        SUPPORTED_CHARGE_BASES,
        row_number=row_number,
        column="charge_basis",
    )
    normalized["billing_frequency"] = _parse_supported_value(
        normalized["billing_frequency"],
        SUPPORTED_BILLING_FREQUENCIES,
        row_number=row_number,
        column="billing_frequency",
    )
    _validate_cost_frequency(normalized["cost_type"], normalized["billing_frequency"], row_number=row_number)
    normalized["record_type"] = _parse_supported_value(
        normalized["record_type"],
        SUPPORTED_RECORD_TYPES,
        row_number=row_number,
        column="record_type",
    )
    normalized["quantity"] = _parse_non_negative_decimal(
        normalized["quantity"],
        row_number=row_number,
        column="quantity",
    )
    unit_cost = _parse_non_negative_decimal(
        normalized["unit_cost"],
        row_number=row_number,
        column="unit_cost",
    )
    currency = _parse_supported_value(
        normalized["currency"],
        SUPPORTED_COST_CURRENCIES,
        row_number=row_number,
        column="currency",
        normalize_upper=True,
    )
    normalized["unit_cost"] = convert_to_mxn(unit_cost, currency)
    normalized["currency"] = BASE_CURRENCY
    normalized["entered_unit_cost"] = unit_cost
    normalized["entered_currency"] = currency
    normalized["start_date"] = _parse_optional_iso_date(
        normalized["start_date"],
        row_number=row_number,
        column="start_date",
    )
    normalized["end_date"] = _parse_optional_iso_date(normalized["end_date"], row_number=row_number, column="end_date")
    normalized["enabled"] = _parse_bool(normalized["enabled"], row_number=row_number, column="enabled")
    normalized["cost_key"] = normalized["cost_key"] or _derived_cost_key(normalized)
    return normalized


def _validate_cost_frequency(cost_type: str, billing_frequency: str, *, row_number: int) -> None:
    if cost_type == "variable" and billing_frequency != "usage":
        raise ValueError(f"seed_costs.csv row {row_number} variable costs must use billing_frequency 'usage'")
    if cost_type == "fixed" and billing_frequency == "usage":
        raise ValueError(f"seed_costs.csv row {row_number} billing_frequency 'usage' requires cost_type 'variable'")


def _blank_to_none(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _required_text(value, *, row_number: int, column: str) -> str:
    if value is None:
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' is required")
    return str(value).strip()


def _parse_supported_value(
    value,
    supported: set[str],
    *,
    row_number: int,
    column: str,
    normalize_upper: bool = False,
) -> str:
    text = _required_text(value, row_number=row_number, column=column)
    if normalize_upper:
        text = text.upper()
    if text not in supported:
        allowed = ", ".join(sorted(supported))
        raise ValueError(
            f"seed_costs.csv row {row_number} column '{column}' has unsupported value '{text}'. Use: {allowed}"
        )
    return text


def _parse_positive_int(value, *, row_number: int, column: str) -> int:
    text = _required_text(value, row_number=row_number, column=column)
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' must be positive")
    return parsed


def _parse_optional_positive_int(value, *, default: int, row_number: int, column: str) -> int:
    if value is None:
        return default
    return _parse_positive_int(value, row_number=row_number, column=column)


def _parse_non_negative_decimal(value, *, row_number: int, column: str) -> Decimal:
    text = _required_text(value, row_number=row_number, column=column)
    try:
        parsed = Decimal(text)
    except Exception as exc:
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' cannot be negative")
    return parsed


def _parse_optional_iso_date(value, *, row_number: int, column: str) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError(f"seed_costs.csv row {row_number} column '{column}' must be a valid date")
    return parsed.date()


def _parse_bool(value, *, row_number: int, column: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _required_text(value, row_number=row_number, column=column).lower()
    if text in {"true", "t", "yes", "y", "1", "on"}:
        return True
    if text in {"false", "f", "no", "n", "0", "off"}:
        return False
    raise ValueError(f"seed_costs.csv row {row_number} column '{column}' must be a Boolean value")


def _derived_cost_key(record: dict) -> str:
    parts = [
        record.get("category"),
        record.get("provider"),
        record.get("name"),
        record.get("unit") if record.get("charge_basis") == "usage" else None,
    ]
    raw_key = ".".join(str(part) for part in parts if part)
    return _slug(raw_key)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", ".", value.lower())
    return normalized.strip(".")


def _date_record(record: dict, keys: list[str]) -> dict:
    for key in keys:
        if pd.isna(record.get(key)):
            record[key] = None
        elif hasattr(record[key], "date"):
            record[key] = record[key].date()
    return record


def _parse_dates(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    iso_mask = values.str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)
    parsed.loc[iso_mask] = pd.to_datetime(values.loc[iso_mask], format="%Y-%m-%d", errors="coerce")
    parsed.loc[~iso_mask] = pd.to_datetime(values.loc[~iso_mask], errors="coerce", dayfirst=True)
    return parsed


def _validate_cost_versions(items: list[CostItem]) -> None:
    versions: dict[str, list[CostItem]] = defaultdict(list)
    for item in items:
        if item.enabled and item.record_type == "actual":
            versions[item.cost_key].append(item)
    for cost_key, cost_versions in versions.items():
        ordered = sorted(cost_versions, key=lambda item: item.start_date or date.min)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end_date is None or current.start_date is None or current.start_date <= previous.end_date:
                raise ValueError(f"Overlapping effective dates for cost_key '{cost_key}'")


def _service_label(service_code: str) -> str:
    labels = {"saremi": "SAREMI", "graphos": "Graphos", "blockchain": "Blockchain / BaaS", "sigen": "SIGEN"}
    return labels.get(service_code, service_code)


def _event_revenue(event_type: str, quantity: Decimal, plan: PricingPlan) -> Decimal:
    price_map = {
        "saremi.document_validation": plan.price_per_document,
        "saremi.ine_validation": plan.price_per_validation,
        "graphos.query": plan.price_per_graph_query,
        "graphos.case_analysis": plan.price_per_graph_query,
        "blockchain.asiento_registration": plan.price_per_blockchain_transaction,
        "blockchain.folio_mint": plan.price_per_property_mint,
    }
    return Decimal(str(quantity)) * Decimal(str(price_map.get(event_type, Decimal("0"))))
