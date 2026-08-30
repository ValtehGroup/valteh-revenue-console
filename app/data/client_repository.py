from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.data.database import SessionLocal
from app.data.schemas import (
    ClientExternalReferenceORM,
    ClientORM,
    ClientSubscriptionORM,
    PricingPlanORM,
    RevenueEventORM,
    UsageEventORM,
)
from app.domain.models import Client, ClientExternalReference, ClientSubscription

logger = logging.getLogger(__name__)

CLIENT_CODE_PATTERN = re.compile(r"^(?:client|test)_\d{4,}$")
SUPPORTED_CLIENT_STATUSES = {"active", "inactive"}


class ClientManagementError(Exception):
    """Safe client-management error suitable for display in the UI."""


class ClientValidationError(ClientManagementError):
    pass


class ClientNotFoundError(ClientManagementError):
    pass


class ClientConcurrencyError(ClientManagementError):
    pass


class ClientReferenceConflictError(ClientManagementError):
    pass


@dataclass(frozen=True)
class ClientCommand:
    name: str
    client_type: str
    start_date: date | str
    notes: str | None = None
    source_system: str | None = None
    external_client_reference: str | None = None
    pricing_plan_id: int | str | None = None
    contract_terms: ContractTermsOverride | None = None


@dataclass(frozen=True)
class ContractTermsOverride:
    monthly_fee: Decimal | str | None = None
    annual_fee: Decimal | str | None = None
    included_documents: int | str | None = None
    overage_price: Decimal | str | None = None
    setup_fee: Decimal | str | None = None
    setup_disposition: str | None = None
    one_time_fee: Decimal | str | None = None
    minimum_term_months: int | str | None = None
    discount_percentage: Decimal | str | None = None
    discount_reason: str | None = None
    approved_by: str | None = None
    channel_partner_code: str | None = None
    channel_commission_pct: Decimal | str | None = None


@dataclass(frozen=True)
class ClientUpdateCommand:
    name: str
    client_type: str
    start_date: date | str
    notes: str | None = None


SessionFactory = Callable[[], Session]


class ClientRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal):
        self._session_factory = session_factory

    def list_clients(self, status: str = "all") -> list[Client]:
        if status not in {"all", *SUPPORTED_CLIENT_STATUSES}:
            raise ClientValidationError("Status must be all, active, or inactive.")
        with self._session_factory() as session:
            statement = select(ClientORM)
            if status != "all":
                statement = statement.where(ClientORM.status == status)
            rows = session.scalars(statement.order_by(ClientORM.updated_at.desc(), ClientORM.id.desc())).all()
            return [_to_client(row) for row in rows]

    def get_client(self, client_id: int) -> Client:
        with self._session_factory() as session:
            return _to_client(self._get_client_row(session, client_id))

    def get_client_by_code(self, client_code: str) -> Client:
        normalized = _validate_client_code(client_code)
        with self._session_factory() as session:
            row = session.scalar(select(ClientORM).where(ClientORM.client_code == normalized))
            if row is None:
                raise ClientNotFoundError(f"Client '{normalized}' was not found.")
            return _to_client(row)

    def create_client(self, command: ClientCommand) -> Client:
        values = _validate_client_command(command)
        with self._session_factory() as session:
            try:
                with session.begin():
                    now = _utc_now()
                    row = ClientORM(
                        client_code=f"pending-{uuid4().hex}",
                        name=values["name"],
                        client_type=values["client_type"],
                        status="active",
                        start_date=values["start_date"],
                        end_date=None,
                        notes=values["notes"],
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    row.client_code = format_client_code(row.id)
                    if values["pricing_plan_id"] is not None:
                        pricing_plan = session.get(PricingPlanORM, values["pricing_plan_id"])
                        if pricing_plan is None:
                            raise ClientValidationError("The selected pricing plan is no longer available.")
                        if pricing_plan.dedicated_client_id is not None:
                            raise ClientValidationError(
                                "Client-specific pricing plans cannot be assigned during client creation."
                            )
                        _validate_assignable_plan(pricing_plan, row.id, row.start_date)
                        session.add(
                            _subscription_snapshot(row.id, pricing_plan, row.start_date, now, command.contract_terms)
                        )
                    if values["source_system"]:
                        self._add_reference_row(
                            session,
                            row.id,
                            values["source_system"],
                            values["external_client_reference"],
                            now,
                        )
                session.refresh(row)
                return _to_client(row)
            except ClientManagementError:
                raise
            except IntegrityError as exc:
                logger.warning("Client creation conflict", exc_info=True)
                if _is_reference_conflict(exc):
                    raise ClientReferenceConflictError(
                        "This external client reference is already assigned for that source system."
                    ) from exc
                raise ClientValidationError("The client conflicts with an existing record.") from exc
            except SQLAlchemyError as exc:
                logger.exception("Client creation failed")
                raise ClientManagementError("The client could not be saved. Please try again.") from exc

    def update_client(
        self,
        client_id: int,
        command: ClientUpdateCommand,
        expected_updated_at: datetime | str,
    ) -> Client:
        values = _validate_client_update(command)
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_client_row(session, client_id)
                    self._assert_fresh(row, expected_updated_at)
                    self._validate_start_date_against_history(session, client_id, values["start_date"])
                    if row.end_date and values["start_date"] > row.end_date:
                        raise ClientValidationError("Start date cannot be after the client's end date.")
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = _next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_client(row)
            except ClientManagementError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("Client update failed", extra={"client_id": client_id})
                raise ClientManagementError("The client could not be updated. Please try again.") from exc

    def change_pricing_plan(
        self,
        client_id: int,
        pricing_plan_id: int | str,
        effective_from: date | str,
        expected_updated_at: datetime | str,
        contract_terms: ContractTermsOverride | None = None,
    ) -> ClientSubscription:
        plan_id = _optional_positive_int(pricing_plan_id, "pricing_plan_id")
        effective_date = _parse_date(effective_from, "effective_from", required=True)
        if plan_id is None:
            raise ClientValidationError("Pricing plan is required.")
        with self._session_factory() as session:
            try:
                with session.begin():
                    client = self._get_client_row(session, client_id)
                    self._assert_fresh(client, expected_updated_at)
                    if client.status != "active":
                        raise ClientValidationError("Reactivate the client before changing its pricing plan.")
                    if effective_date < client.start_date:
                        raise ClientValidationError("Effective from cannot precede the client's start date.")
                    if client.end_date is not None and effective_date > client.end_date:
                        raise ClientValidationError("Effective from cannot be after the client's end date.")
                    plan = session.get(PricingPlanORM, plan_id)
                    if plan is None:
                        raise ClientValidationError("The selected pricing plan is no longer available.")
                    _validate_assignable_plan(plan, client_id, effective_date)

                    subscriptions = session.scalars(
                        select(ClientSubscriptionORM)
                        .where(ClientSubscriptionORM.client_id == client_id)
                        .order_by(ClientSubscriptionORM.start_date, ClientSubscriptionORM.id)
                    ).all()
                    if any(subscription.start_date >= effective_date for subscription in subscriptions):
                        raise ClientValidationError(
                            "Effective from must be after all existing or scheduled subscription start dates."
                        )
                    previous = next(
                        (
                            subscription
                            for subscription in reversed(subscriptions)
                            if subscription.start_date < effective_date
                            and (subscription.end_date is None or subscription.end_date >= effective_date)
                        ),
                        None,
                    )
                    if previous is not None:
                        if previous.pricing_plan_id == plan_id:
                            raise ClientValidationError("The client already uses the selected pricing plan.")
                        previous.end_date = effective_date - timedelta(days=1)
                        previous.status = "inactive"

                    new_subscription = _subscription_snapshot(
                        client_id,
                        plan,
                        effective_date,
                        _utc_now(),
                        contract_terms,
                    )
                    session.add(new_subscription)
                    client.updated_at = _next_updated_at(client.updated_at)
                    session.flush()
                session.refresh(new_subscription)
                return ClientSubscription.model_validate(
                    {
                        column.name: getattr(new_subscription, column.name)
                        for column in ClientSubscriptionORM.__table__.columns
                    }
                )
            except ClientManagementError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("Pricing plan change failed", extra={"client_id": client_id})
                raise ClientManagementError("The pricing plan could not be changed. Please try again.") from exc

    def deactivate_client(
        self,
        client_id: int,
        end_date: date | str,
        expected_updated_at: datetime | str,
    ) -> Client:
        parsed_end = _parse_date(end_date, "end_date", required=True)
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_client_row(session, client_id)
                    self._assert_fresh(row, expected_updated_at)
                    if row.status == "inactive":
                        raise ClientValidationError("This client is already inactive.")
                    if parsed_end < row.start_date:
                        raise ClientValidationError("End date must be on or after the client's start date.")
                    active_subscriptions = session.scalars(
                        select(ClientSubscriptionORM).where(
                            ClientSubscriptionORM.client_id == client_id,
                            ClientSubscriptionORM.status == "active",
                        )
                    ).all()
                    if any(subscription.start_date > parsed_end for subscription in active_subscriptions):
                        raise ClientValidationError("End date cannot precede an active subscription's start date.")
                    now = _next_updated_at(row.updated_at)
                    row.status = "inactive"
                    row.end_date = parsed_end
                    row.updated_at = now
                    for subscription in active_subscriptions:
                        if subscription.end_date is None or subscription.end_date > parsed_end:
                            subscription.end_date = parsed_end
                        subscription.status = "inactive"
                session.refresh(row)
                return _to_client(row)
            except ClientManagementError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("Client deactivation failed", extra={"client_id": client_id})
                raise ClientManagementError("The client could not be deactivated. Please try again.") from exc

    def reactivate_client(self, client_id: int, expected_updated_at: datetime | str) -> Client:
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = self._get_client_row(session, client_id)
                    self._assert_fresh(row, expected_updated_at)
                    if row.status == "active":
                        raise ClientValidationError("This client is already active.")
                    row.status = "active"
                    row.end_date = None
                    row.updated_at = _next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_client(row)
            except ClientManagementError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("Client reactivation failed", extra={"client_id": client_id})
                raise ClientManagementError("The client could not be reactivated. Please try again.") from exc

    def list_references(self, client_id: int, *, include_inactive: bool = True) -> list[ClientExternalReference]:
        with self._session_factory() as session:
            self._get_client_row(session, client_id)
            statement = select(ClientExternalReferenceORM).where(ClientExternalReferenceORM.client_id == client_id)
            if not include_inactive:
                statement = statement.where(ClientExternalReferenceORM.enabled.is_(True))
            rows = session.scalars(statement.order_by(ClientExternalReferenceORM.source_system)).all()
            return [_to_reference(row) for row in rows]

    def add_reference(
        self, client_id: int, source_system: str, external_client_reference: str
    ) -> ClientExternalReference:
        source, reference = _validate_reference(source_system, external_client_reference)
        with self._session_factory() as session:
            try:
                with session.begin():
                    self._get_client_row(session, client_id)
                    row = self._add_reference_row(session, client_id, source, reference, _utc_now())
                session.refresh(row)
                return _to_reference(row)
            except ClientManagementError:
                raise
            except IntegrityError as exc:
                logger.warning("External client reference conflict", extra={"client_id": client_id})
                raise ClientReferenceConflictError(
                    "This external client reference is already assigned for that source system."
                ) from exc
            except SQLAlchemyError as exc:
                logger.exception("External client reference creation failed", extra={"client_id": client_id})
                raise ClientManagementError("The external reference could not be saved. Please try again.") from exc

    def deactivate_reference(self, reference_id: int) -> ClientExternalReference:
        with self._session_factory() as session:
            try:
                with session.begin():
                    row = session.get(ClientExternalReferenceORM, reference_id)
                    if row is None:
                        raise ClientNotFoundError(f"External reference {reference_id} was not found.")
                    row.enabled = False
                    row.updated_at = _next_updated_at(row.updated_at)
                session.refresh(row)
                return _to_reference(row)
            except ClientManagementError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("External client reference deactivation failed", extra={"reference_id": reference_id})
                raise ClientManagementError("The external reference could not be deactivated.") from exc

    def resolve_client_reference(self, source_system: str, external_reference: str) -> int | None:
        with self._session_factory() as session:
            return self.resolve_client_reference_in_session(session, source_system, external_reference)

    @staticmethod
    def resolve_client_reference_in_session(
        session: Session, source_system: str, external_reference: str
    ) -> int | None:
        """Resolve a source-scoped reference inside an existing transaction."""

        source, reference = _validate_reference(source_system, external_reference)
        return session.scalar(
            select(ClientExternalReferenceORM.client_id).where(
                ClientExternalReferenceORM.source_system == source,
                ClientExternalReferenceORM.external_client_reference == reference,
                ClientExternalReferenceORM.enabled.is_(True),
            )
        )

    @staticmethod
    def _get_client_row(session: Session, client_id: int) -> ClientORM:
        row = session.get(ClientORM, client_id)
        if row is None:
            raise ClientNotFoundError(f"Client {client_id} was not found.")
        return row

    @staticmethod
    def _assert_fresh(row: ClientORM, expected: datetime | str) -> None:
        if _normalize_datetime(row.updated_at) != _normalize_datetime(expected):
            raise ClientConcurrencyError("This client was changed by another user. Refresh and try again.")

    @staticmethod
    def _add_reference_row(
        session: Session,
        client_id: int,
        source_system: str,
        external_client_reference: str,
        now: datetime,
    ) -> ClientExternalReferenceORM:
        row = ClientExternalReferenceORM(
            client_id=client_id,
            source_system=source_system,
            external_client_reference=external_client_reference,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def _validate_start_date_against_history(session: Session, client_id: int, proposed_start: date) -> None:
        dates: list[date] = []
        subscription_date = session.scalar(
            select(func.min(ClientSubscriptionORM.start_date)).where(ClientSubscriptionORM.client_id == client_id)
        )
        usage_date = session.scalar(
            select(func.min(UsageEventORM.event_timestamp)).where(UsageEventORM.client_id == client_id)
        )
        revenue_date = session.scalar(
            select(func.min(RevenueEventORM.event_timestamp)).where(RevenueEventORM.client_id == client_id)
        )
        if subscription_date:
            dates.append(subscription_date)
        if usage_date:
            dates.append(usage_date.date())
        if revenue_date:
            dates.append(revenue_date.date())
        if dates and proposed_start > min(dates):
            raise ClientValidationError("Start date cannot be later than the client's existing history.")


def format_client_code(client_id: int) -> str:
    return f"client_{client_id:04d}"


def _validate_client_command(command: ClientCommand) -> dict[str, Any]:
    source, reference = _optional_reference(command.source_system, command.external_client_reference)
    return {
        **_validate_client_update(
            ClientUpdateCommand(command.name, command.client_type, command.start_date, command.notes)
        ),
        "source_system": source,
        "external_client_reference": reference,
        "pricing_plan_id": _optional_positive_int(command.pricing_plan_id, "pricing_plan_id"),
    }


def _validate_assignable_plan(plan: PricingPlanORM, client_id: int, effective_date: date) -> None:
    if plan.dedicated_client_id is not None and plan.dedicated_client_id != client_id:
        raise ClientValidationError("The selected pricing plan is dedicated to another client.")
    if not plan.assignable or plan.status != "active":
        raise ClientValidationError("The selected pricing plan is informational and cannot be assigned.")
    if plan.assignment_requires_approval:
        raise ClientValidationError("The selected pricing plan requires commercial approval before assignment.")
    if plan.effective_from is not None and effective_date < plan.effective_from:
        raise ClientValidationError("The selected pricing version is not effective on that date.")
    if plan.effective_to is not None and effective_date > plan.effective_to:
        raise ClientValidationError("The selected pricing version is no longer effective on that date.")
    if effective_date.day != 1:
        raise ClientValidationError("New commercial agreements must start on the first day of a billing month.")


def _subscription_snapshot(
    client_id: int,
    plan: PricingPlanORM,
    effective_date: date,
    now: datetime,
    override: ContractTermsOverride | None,
) -> ClientSubscriptionORM:
    terms = override or ContractTermsOverride()
    if plan.pricing_model == "custom":
        required = {
            "monthly fee": terms.monthly_fee,
            "included documents": terms.included_documents,
            "overage price": terms.overage_price,
            "setup fee": terms.setup_fee,
            "setup disposition": terms.setup_disposition,
            "one-time fee": terms.one_time_fee,
        }
        missing = [label for label, value in required.items() if value in (None, "")]
        if missing:
            raise ClientValidationError(f"Custom contracts require explicit {', '.join(missing)}.")
    setup_disposition = terms.setup_disposition or ("charged" if Decimal(plan.setup_fee or 0) > 0 else "not_applicable")
    if setup_disposition not in {"charged", "included", "waived", "not_applicable"}:
        raise ClientValidationError("Setup disposition is invalid.")
    setup_fee = _contract_decimal(terms.setup_fee, plan.setup_fee)
    if setup_disposition != "charged":
        setup_fee = Decimal("0")
    minimum_setup = Decimal(plan.minimum_setup_fee or 0)
    approved_by = _clean_text(terms.approved_by, "approved_by")
    discount_reason = _clean_text(terms.discount_reason, "discount_reason")
    if setup_disposition == "charged" and setup_fee < minimum_setup and (not approved_by or not discount_reason):
        raise ClientValidationError("Setup below the catalog minimum requires a reason and an approver.")
    included_documents = _contract_int(terms.included_documents, plan.included_documents)
    return ClientSubscriptionORM(
        client_id=client_id,
        pricing_plan_id=plan.id,
        start_date=effective_date,
        status="active",
        contracted_monthly_fee=_contract_decimal(terms.monthly_fee, plan.monthly_fixed_fee),
        contracted_annual_fee=_contract_decimal(terms.annual_fee, plan.annual_fee),
        contracted_included_documents=included_documents,
        contracted_overage_price=_contract_decimal(terms.overage_price, plan.price_per_document),
        contracted_setup_fee=setup_fee,
        setup_disposition=setup_disposition,
        contracted_one_time_fee=_contract_decimal(terms.one_time_fee, plan.one_time_fee),
        currency=plan.currency,
        billing_cycle_anchor=effective_date,
        minimum_term_months=_contract_int(terms.minimum_term_months, 0),
        discount_percentage=_contract_decimal(terms.discount_percentage, 0),
        discount_reason=discount_reason,
        approved_by=approved_by,
        channel_partner_code=_clean_text(terms.channel_partner_code, "channel_partner_code"),
        channel_commission_pct=_contract_decimal(terms.channel_commission_pct, 0),
        data_origin="production",
        usage_data_status="pending",
        created_at=now,
        updated_at=now,
    )


def _contract_decimal(value: Any, default: Any) -> Decimal:
    candidate = default if value in (None, "") else value
    try:
        parsed = Decimal(str(candidate or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ClientValidationError("Contract monetary terms must be valid non-negative numbers.") from exc
    if parsed < 0:
        raise ClientValidationError("Contract monetary terms cannot be negative.")
    return parsed


def _contract_int(value: Any, default: Any) -> int:
    candidate = default if value in (None, "") else value
    try:
        parsed = int(candidate or 0)
    except (TypeError, ValueError) as exc:
        raise ClientValidationError("Contract quantities must be valid non-negative integers.") from exc
    if parsed < 0:
        raise ClientValidationError("Contract quantities cannot be negative.")
    return parsed


def _validate_client_update(command: ClientUpdateCommand) -> dict[str, Any]:
    return {
        "name": _clean_text(command.name, "name", required=True),
        "client_type": _clean_text(command.client_type, "client_type", required=True),
        "start_date": _parse_date(command.start_date, "start_date", required=True),
        "notes": _clean_text(command.notes, "notes"),
    }


def _optional_reference(source_system: Any, external_reference: Any) -> tuple[str | None, str | None]:
    source = _clean_text(source_system, "source_system")
    reference = _clean_text(external_reference, "external_client_reference")
    if bool(source) != bool(reference):
        raise ClientValidationError("Source system and external client reference must be provided together.")
    return (_normalize_source(source), reference) if source and reference else (None, None)


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ClientValidationError(f"{field.replace('_', ' ').title()} must be a valid selection.") from exc
    if parsed <= 0:
        raise ClientValidationError(f"{field.replace('_', ' ').title()} must be a valid selection.")
    return parsed


def _validate_reference(source_system: Any, external_reference: Any) -> tuple[str, str]:
    source = _clean_text(source_system, "source_system", required=True)
    reference = _clean_text(external_reference, "external_client_reference", required=True)
    return _normalize_source(source), reference


def _normalize_source(value: str) -> str:
    return value.strip().lower()


def _validate_client_code(value: str) -> str:
    code = _clean_text(value, "client_code", required=True)
    if not CLIENT_CODE_PATTERN.fullmatch(code):
        raise ClientValidationError("Client ID must use the format client_0001 or test_0001.")
    return code


def _clean_text(value: Any, field: str, required: bool = False) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    if required and not text:
        raise ClientValidationError(f"{field.replace('_', ' ').title()} is required.")
    return text or None


def _parse_date(value: Any, field: str, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ClientValidationError(f"{field.replace('_', ' ').title()} is required.")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ClientValidationError(f"{field.replace('_', ' ').title()} must be a valid ISO date.") from exc


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_datetime(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _next_updated_at(previous: datetime) -> datetime:
    return max(_utc_now(), _normalize_datetime(previous) + timedelta(microseconds=1))


def _to_client(row: ClientORM) -> Client:
    values = {column.name: getattr(row, column.name) for column in ClientORM.__table__.columns}
    values["created_at"] = _normalize_datetime(values["created_at"])
    values["updated_at"] = _normalize_datetime(values["updated_at"])
    return Client.model_validate(values)


def _to_reference(row: ClientExternalReferenceORM) -> ClientExternalReference:
    values = {column.name: getattr(row, column.name) for column in ClientExternalReferenceORM.__table__.columns}
    values["created_at"] = _normalize_datetime(values["created_at"])
    values["updated_at"] = _normalize_datetime(values["updated_at"])
    return ClientExternalReference.model_validate(values)


def _is_reference_conflict(exc: IntegrityError) -> bool:
    return "external" in str(exc.orig).lower() or "source_system" in str(exc.orig).lower()
