from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.data.database import SessionLocal
from app.data.schemas import CostItemORM
from app.domain.models import CostItem
from app.utils.currency import BASE_CURRENCY, STATIC_EXCHANGE_RATES_TO_MXN, convert_to_mxn

SUPPORTED_COST_TYPES = {"fixed", "variable"}
SUPPORTED_CHARGE_BASES = {"flat", "per_user", "usage"}
SUPPORTED_BILLING_FREQUENCIES = {"monthly", "annual", "usage", "once"}
SUPPORTED_RECORD_TYPES = {"actual", "budget", "estimate"}
UNCHANGED = object()


class CostManagementError(Exception):
    """Safe domain-level error suitable for presentation to a user."""


class CostValidationError(CostManagementError):
    pass


class CostNotFoundError(CostManagementError):
    pass


class CostConcurrencyError(CostManagementError):
    pass


@dataclass(frozen=True)
class CostCommand:
    name: str
    provider: str | None
    category: str
    service_line: str | None
    cost_type: str
    charge_basis: str
    quantity: Decimal | str
    unit_cost: Decimal | str
    currency: str
    unit: str
    billing_frequency: str
    start_date: date | str
    end_date: date | str | None = None
    record_type: str = "actual"
    notes: str | None = None
    cost_key: str | None = None


@dataclass(frozen=True)
class MetadataCommand:
    name: str
    provider: str | None
    category: str
    service_line: str | None
    notes: str | None
    start_date: date | str | None | object = UNCHANGED
    end_date: date | str | None | object = UNCHANGED


SessionFactory = Callable[[], Session]


class CostRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal):
        self._session_factory = session_factory

    def list_costs(self, status: str = "all") -> list[CostItem]:
        if status not in {"all", "active", "inactive"}:
            raise CostValidationError("Status must be all, active, or inactive.")
        with self._session_factory() as session:
            statement = select(CostItemORM)
            if status == "active":
                statement = statement.where(CostItemORM.enabled.is_(True))
            elif status == "inactive":
                statement = statement.where(CostItemORM.enabled.is_(False))
            rows = session.scalars(statement.order_by(CostItemORM.updated_at.desc(), CostItemORM.id.desc())).all()
            return [_to_domain(row) for row in rows]

    def get_cost(self, record_id: int) -> CostItem:
        with self._session_factory() as session:
            return _to_domain(self._get_row(session, record_id))

    def create_cost(self, command: CostCommand) -> CostItem:
        values = validate_cost_command(command)
        generate_key = values["cost_key"] is None
        if generate_key:
            values["cost_key"] = f"pending-{uuid4()}"
        with self._session_factory() as session:
            try:
                with session.begin():
                    self._assert_no_overlap(session, values)
                    now = utc_now()
                    row = CostItemORM(**values, created_at=now, updated_at=now)
                    session.add(row)
                    session.flush()
                    if generate_key:
                        row.cost_key = format_cost_key(row.id, row.name, row.provider, row.category)
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except IntegrityError as exc:
                raise CostValidationError("The cost conflicts with an existing record.") from exc
            except SQLAlchemyError as exc:
                raise CostManagementError("The cost could not be saved. Please try again.") from exc

    def update_cost_metadata(
        self, record_id: int, command: MetadataCommand, expected_updated_at: datetime | str
    ) -> CostItem:
        values = validate_metadata_command(command)
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_row(session, record_id)
                    self._assert_fresh(row, expected_updated_at)
                    proposed_start = values.get("start_date", row.start_date)
                    proposed_end = values.get("end_date", row.end_date)
                    if proposed_start and proposed_end and proposed_end < proposed_start:
                        raise CostValidationError("End date must be on or after the start date.")
                    lifecycle = {
                        "cost_key": row.cost_key,
                        "record_type": row.record_type,
                        "enabled": row.enabled,
                        "start_date": proposed_start,
                        "end_date": proposed_end,
                    }
                    self._assert_no_overlap(session, lifecycle, excluded_ids={row.id})
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except SQLAlchemyError as exc:
                raise CostManagementError("The cost metadata could not be saved. Please try again.") from exc

    def create_cost_version(
        self,
        record_id: int,
        changes: dict[str, Any],
        effective_from: date | str,
        expected_updated_at: datetime | str,
    ) -> CostItem:
        effective_date = parse_date(effective_from, "effective_from", required=True)
        with self._session_factory() as session:
            try:
                with session.begin():
                    previous = self._get_row(session, record_id)
                    self._assert_fresh(previous, expected_updated_at)
                    if previous.start_date is None or effective_date <= previous.start_date:
                        raise CostValidationError("Effective from must be after the selected version's start date.")
                    if previous.end_date is not None and effective_date > previous.end_date:
                        raise CostValidationError("Effective from must fall within the selected version's lifecycle.")
                    source = {field.name: getattr(previous, field.name) for field in fields(CostCommand)}
                    source.update(changes)
                    source.update(cost_key=previous.cost_key, start_date=effective_date, end_date=None)
                    values = validate_cost_command(CostCommand(**source))
                    self._assert_no_overlap(session, values, excluded_ids={record_id})
                    now = next_updated_at(previous.updated_at)
                    previous.end_date = effective_date - timedelta(days=1)
                    previous.updated_at = now
                    row = CostItemORM(**values, created_at=now, updated_at=now)
                    session.add(row)
                    session.flush()
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except (TypeError, IntegrityError) as exc:
                raise CostValidationError("The proposed cost version is invalid.") from exc
            except SQLAlchemyError as exc:
                raise CostManagementError("The new cost version could not be saved. Please try again.") from exc

    def end_cost(self, record_id: int, end_date: date | str, expected_updated_at: datetime | str) -> CostItem:
        parsed_end = parse_date(end_date, "end_date", required=True)
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_row(session, record_id)
                    self._assert_fresh(row, expected_updated_at)
                    if row.start_date and parsed_end < row.start_date:
                        raise CostValidationError("End date must be on or after the start date.")
                    row.end_date = parsed_end
                    row.updated_at = next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except SQLAlchemyError as exc:
                raise CostManagementError("The cost could not be ended. Please try again.") from exc

    def deactivate_cost(self, record_id: int, expected_updated_at: datetime | str) -> CostItem:
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_row(session, record_id)
                    self._assert_fresh(row, expected_updated_at)
                    row.enabled = False
                    row.updated_at = next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except SQLAlchemyError as exc:
                raise CostManagementError("The cost could not be deactivated. Please try again.") from exc

    def reactivate_cost(self, record_id: int, expected_updated_at: datetime | str) -> CostItem:
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_row(session, record_id)
                    self._assert_fresh(row, expected_updated_at)
                    if row.enabled:
                        raise CostValidationError("This cost record is already active.")
                    values = {column.name: getattr(row, column.name) for column in CostItemORM.__table__.columns}
                    values["enabled"] = True
                    self._assert_no_overlap(session, values, excluded_ids={row.id})
                    row.enabled = True
                    row.updated_at = next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_domain(row)
            except CostManagementError:
                raise
            except SQLAlchemyError as exc:
                raise CostManagementError("The cost could not be reactivated. Please try again.") from exc

    def count(self) -> int:
        with self._session_factory() as session:
            return session.scalar(select(func.count()).select_from(CostItemORM)) or 0

    @staticmethod
    def _get_row(session: Session, record_id: int) -> CostItemORM:
        row = session.get(CostItemORM, record_id)
        if row is None:
            raise CostNotFoundError(f"Cost record {record_id} was not found. Refresh and try again.")
        return row

    @staticmethod
    def _assert_fresh(row: CostItemORM, expected: datetime | str) -> None:
        if normalize_datetime(row.updated_at) != normalize_datetime(expected):
            raise CostConcurrencyError("This cost was changed by another user. Refresh and try again.")

    @staticmethod
    def _assert_no_overlap(session: Session, values: dict[str, Any], excluded_ids: set[int] | None = None) -> None:
        if not values["enabled"] if "enabled" in values else False:
            return
        if values["record_type"] != "actual":
            return
        statement = select(CostItemORM).where(
            CostItemORM.cost_key == values["cost_key"],
            CostItemORM.enabled.is_(True),
            CostItemORM.record_type == "actual",
        )
        if excluded_ids:
            statement = statement.where(CostItemORM.id.not_in(excluded_ids))
        for existing in session.scalars(statement):
            if dates_overlap(values["start_date"], values["end_date"], existing.start_date, existing.end_date):
                raise CostValidationError(f"Effective dates overlap another active version of '{values['cost_key']}'.")


def validate_cost_command(command: CostCommand) -> dict[str, Any]:
    required_text = ("name", "category", "unit")
    values = {field.name: getattr(command, field.name) for field in fields(command)}
    for key in required_text:
        values[key] = clean_text(values[key], key, required=True)
    for key in ("provider", "service_line", "notes"):
        values[key] = clean_text(values[key], key)
    values["cost_type"] = supported(values["cost_type"], SUPPORTED_COST_TYPES, "cost_type")
    values["charge_basis"] = supported(values["charge_basis"], SUPPORTED_CHARGE_BASES, "charge_basis")
    values["billing_frequency"] = supported(
        values["billing_frequency"], SUPPORTED_BILLING_FREQUENCIES, "billing_frequency"
    )
    validate_type_frequency(values["cost_type"], values["billing_frequency"])
    values["record_type"] = supported(values["record_type"], SUPPORTED_RECORD_TYPES, "record_type")
    values["quantity"] = non_negative_decimal(values["quantity"], "quantity")
    unit_cost = non_negative_decimal(values["unit_cost"], "unit_cost")
    currency = supported(str(values["currency"]).upper(), set(STATIC_EXCHANGE_RATES_TO_MXN), "currency")
    values["unit_cost"] = convert_to_mxn(unit_cost, currency)
    values["currency"] = BASE_CURRENCY
    values["entered_unit_cost"] = unit_cost
    values["entered_currency"] = currency
    values["start_date"] = parse_date(values["start_date"], "start_date", required=True)
    values["end_date"] = parse_date(values["end_date"], "end_date")
    if values["end_date"] and values["end_date"] < values["start_date"]:
        raise CostValidationError("End date must be on or after the start date.")
    values["cost_key"] = clean_text(values["cost_key"], "cost_key")
    if values["cost_key"] and len(values["cost_key"]) > 120:
        raise CostValidationError("Cost key cannot exceed 120 characters.")
    values["enabled"] = True
    return values


def validate_type_frequency(cost_type: str, billing_frequency: str) -> None:
    if cost_type == "variable" and billing_frequency != "usage":
        raise CostValidationError("Variable costs must use Usage billing frequency.")
    if cost_type == "fixed" and billing_frequency == "usage":
        raise CostValidationError("Usage billing frequency requires a Variable cost type.")


def validate_metadata_command(command: MetadataCommand) -> dict[str, Any]:
    values = {
        "name": clean_text(command.name, "name", required=True),
        "provider": clean_text(command.provider, "provider"),
        "category": clean_text(command.category, "category", required=True),
        "service_line": clean_text(command.service_line, "service_line"),
        "notes": clean_text(command.notes, "notes"),
    }
    if command.start_date is not UNCHANGED:
        values["start_date"] = parse_date(command.start_date, "start_date")
    if command.end_date is not UNCHANGED:
        values["end_date"] = parse_date(command.end_date, "end_date")
    return values


def clean_text(value: Any, field: str, required: bool = False) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    if required and not text:
        raise CostValidationError(f"{field.replace('_', ' ').title()} is required.")
    return text or None


def supported(value: Any, allowed: set[str], field: str) -> str:
    text = clean_text(value, field, required=True)
    if text not in allowed:
        raise CostValidationError(f"Unsupported {field.replace('_', ' ')}. Choose: {', '.join(sorted(allowed))}.")
    return text


def non_negative_decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise CostValidationError(f"{field.replace('_', ' ').title()} must be a valid decimal.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise CostValidationError(f"{field.replace('_', ' ').title()} must be a non-negative decimal.")
    return parsed


def parse_date(value: Any, field: str, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise CostValidationError(f"{field.replace('_', ' ').title()} is required.")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CostValidationError(f"{field.replace('_', ' ').title()} must be a valid ISO date.") from exc


def format_cost_key(record_id: int, name: str, provider: str | None, category: str) -> str:
    key = f"{record_id:04d}-{name}-{provider or 'Unassigned'}-{category}"
    if len(key) > 120:
        raise CostValidationError("The generated cost key exceeds 120 characters. Shorten the descriptive fields.")
    return key


def dates_overlap(
    first_start: date | None,
    first_end: date | None,
    second_start: date | None,
    second_end: date | None,
) -> bool:
    return (first_end is None or second_start is None or second_start <= first_end) and (
        second_end is None or first_start is None or first_start <= second_end
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def next_updated_at(previous: datetime) -> datetime:
    return max(utc_now(), normalize_datetime(previous) + timedelta(microseconds=1))


def _to_domain(row: CostItemORM) -> CostItem:
    values = {column.name: getattr(row, column.name) for column in CostItemORM.__table__.columns}
    values["created_at"] = normalize_datetime(values["created_at"])
    values["updated_at"] = normalize_datetime(values["updated_at"])
    return CostItem.model_validate(values)
