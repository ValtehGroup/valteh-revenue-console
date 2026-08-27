from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.data.database import SessionLocal
from app.data.schemas import AnthropicAPIKeyAssignmentORM, ClientExternalReferenceORM, ClientORM

logger = logging.getLogger(__name__)

ENVIRONMENT_SOURCES = {
    "development": "anthropic_development",
    "staging": "anthropic_staging",
    "production": "anthropic_production",
    "internal": "anthropic_internal",
}
SOURCE_ENVIRONMENTS = {source: environment for environment, source in ENVIRONMENT_SOURCES.items()}
ANTHROPIC_API_KEY_ID_PATTERN = re.compile(r"^apikey_[A-Za-z0-9]+$")
ANTHROPIC_HISTORY_START_DATE = date(2026, 7, 1)


class AnthropicAssignmentError(RuntimeError):
    """Safe assignment error suitable for display in the dashboard."""


@dataclass(frozen=True)
class AnthropicKeyAssignment:
    api_key_id: str
    environment: str
    client_id: int
    client_code: str
    client_name: str


@dataclass(frozen=True)
class AnthropicKeyAssignmentCommand:
    api_key_id: str
    environment: str | None
    client_id: int | None


@dataclass(frozen=True)
class AnthropicKeyAssignmentPeriod:
    api_key_id: str
    environment: str
    client_id: int
    client_code: str
    client_name: str
    effective_from: date
    effective_to: date | None


SessionFactory = Callable[[], Session]


class AnthropicAssignmentRepository:
    """Persist API-key ownership through existing source-scoped client references."""

    def __init__(
        self,
        session_factory: SessionFactory = SessionLocal,
        *,
        today: Callable[[], date] | None = None,
    ):
        self._session_factory = session_factory
        self._today = today or (lambda: datetime.now(UTC).date())

    def list_assignments(self) -> list[AnthropicKeyAssignment]:
        with self._session_factory() as session:
            rows = session.execute(
                select(ClientExternalReferenceORM, ClientORM)
                .join(ClientORM, ClientORM.id == ClientExternalReferenceORM.client_id)
                .where(
                    ClientExternalReferenceORM.source_system.in_(SOURCE_ENVIRONMENTS),
                    ClientExternalReferenceORM.enabled.is_(True),
                )
                .order_by(ClientExternalReferenceORM.external_client_reference)
            ).all()
            return [
                AnthropicKeyAssignment(
                    api_key_id=reference.external_client_reference,
                    environment=SOURCE_ENVIRONMENTS[reference.source_system],
                    client_id=client.id,
                    client_code=client.client_code,
                    client_name=client.name,
                )
                for reference, client in rows
            ]

    def save_assignments(self, commands: Sequence[AnthropicKeyAssignmentCommand]) -> list[AnthropicKeyAssignment]:
        normalized = [_validate_command(command) for command in commands]
        with self._session_factory() as session:
            try:
                with session.begin():
                    for command in normalized:
                        self._save_assignment_period(session, command, self._today())
                        self._save_assignment(session, command)
            except AnthropicAssignmentError:
                raise
            except IntegrityError as exc:
                logger.warning("Anthropic API-key assignment conflict", exc_info=True)
                raise AnthropicAssignmentError("An API key conflicts with an existing client assignment.") from exc
            except SQLAlchemyError as exc:
                logger.exception("Anthropic API-key assignments could not be saved")
                raise AnthropicAssignmentError("API-key assignments could not be saved. Please try again.") from exc
        return self.list_assignments()

    def list_assignment_periods(self) -> list[AnthropicKeyAssignmentPeriod]:
        with self._session_factory() as session:
            rows = session.execute(
                select(AnthropicAPIKeyAssignmentORM, ClientORM)
                .join(ClientORM, ClientORM.id == AnthropicAPIKeyAssignmentORM.client_id)
                .order_by(
                    AnthropicAPIKeyAssignmentORM.api_key_id,
                    AnthropicAPIKeyAssignmentORM.effective_from,
                )
            ).all()
            return [
                AnthropicKeyAssignmentPeriod(
                    api_key_id=assignment.api_key_id,
                    environment=assignment.environment,
                    client_id=client.id,
                    client_code=client.client_code,
                    client_name=client.name,
                    effective_from=assignment.effective_from,
                    effective_to=assignment.effective_to,
                )
                for assignment, client in rows
            ]

    @staticmethod
    def _save_assignment_period(session: Session, command: AnthropicKeyAssignmentCommand, today: date) -> None:
        periods = session.scalars(
            select(AnthropicAPIKeyAssignmentORM)
            .where(AnthropicAPIKeyAssignmentORM.api_key_id == command.api_key_id)
            .order_by(AnthropicAPIKeyAssignmentORM.effective_from)
        ).all()
        active = next((period for period in reversed(periods) if period.effective_to is None), None)
        now = datetime.now(UTC)

        current_reference = session.execute(
            select(ClientExternalReferenceORM, ClientORM)
            .join(ClientORM, ClientORM.id == ClientExternalReferenceORM.client_id)
            .where(
                ClientExternalReferenceORM.external_client_reference == command.api_key_id,
                ClientExternalReferenceORM.source_system.in_(SOURCE_ENVIRONMENTS),
                ClientExternalReferenceORM.enabled.is_(True),
            )
        ).first()
        previous_environment = SOURCE_ENVIRONMENTS[current_reference[0].source_system] if current_reference else None
        previous_client_id = current_reference[1].id if current_reference else None

        if active is None:
            if (
                previous_client_id is not None
                and (previous_client_id != command.client_id or previous_environment != command.environment)
                and today > ANTHROPIC_HISTORY_START_DATE
            ):
                session.add(
                    AnthropicAPIKeyAssignmentORM(
                        api_key_id=command.api_key_id,
                        environment=previous_environment,
                        client_id=previous_client_id,
                        effective_from=ANTHROPIC_HISTORY_START_DATE,
                        effective_to=today - timedelta(days=1),
                        created_at=now,
                        updated_at=now,
                    )
                )
            if command.client_id is not None and command.environment is not None:
                effective_from = (
                    today
                    if previous_client_id is not None
                    and (previous_client_id != command.client_id or previous_environment != command.environment)
                    else ANTHROPIC_HISTORY_START_DATE
                )
                session.add(
                    AnthropicAPIKeyAssignmentORM(
                        api_key_id=command.api_key_id,
                        environment=command.environment,
                        client_id=command.client_id,
                        effective_from=effective_from,
                        created_at=now,
                        updated_at=now,
                    )
                )
            return

        if active.client_id == command.client_id and active.environment == command.environment:
            return
        if active.effective_from == today:
            if command.client_id is None or command.environment is None:
                session.delete(active)
            else:
                active.client_id = command.client_id
                active.environment = command.environment
                active.updated_at = now
            return

        active.effective_to = today - timedelta(days=1)
        active.updated_at = now
        if command.client_id is not None and command.environment is not None:
            session.add(
                AnthropicAPIKeyAssignmentORM(
                    api_key_id=command.api_key_id,
                    environment=command.environment,
                    client_id=command.client_id,
                    effective_from=today,
                    created_at=now,
                    updated_at=now,
                )
            )

    @staticmethod
    def _save_assignment(session: Session, command: AnthropicKeyAssignmentCommand) -> None:
        rows = session.scalars(
            select(ClientExternalReferenceORM).where(
                ClientExternalReferenceORM.external_client_reference == command.api_key_id,
                ClientExternalReferenceORM.source_system.in_(SOURCE_ENVIRONMENTS),
            )
        ).all()
        now = datetime.now(UTC)

        if command.client_id is None or command.environment is None:
            for row in rows:
                row.enabled = False
                row.updated_at = now
            return

        if session.get(ClientORM, command.client_id) is None:
            raise AnthropicAssignmentError(f"Client {command.client_id} no longer exists.")

        target_source = ENVIRONMENT_SOURCES[command.environment]
        target = next((row for row in rows if row.source_system == target_source), None)
        if target is None and rows:
            target = rows[0]
            target.source_system = target_source
        elif target is None:
            target = ClientExternalReferenceORM(
                source_system=target_source,
                external_client_reference=command.api_key_id,
                created_at=now,
                updated_at=now,
            )
            session.add(target)

        target.client_id = command.client_id
        target.enabled = True
        target.updated_at = now
        for row in rows:
            if row is not target:
                row.enabled = False
                row.updated_at = now


def _validate_command(command: AnthropicKeyAssignmentCommand) -> AnthropicKeyAssignmentCommand:
    api_key_id = command.api_key_id.strip()
    if not ANTHROPIC_API_KEY_ID_PATTERN.fullmatch(api_key_id):
        raise AnthropicAssignmentError("Anthropic API key ID is invalid.")
    if command.client_id is None:
        return AnthropicKeyAssignmentCommand(api_key_id=api_key_id, environment=None, client_id=None)
    if command.environment not in ENVIRONMENT_SOURCES:
        raise AnthropicAssignmentError("Environment must be development, staging, production, or internal.")
    return AnthropicKeyAssignmentCommand(
        api_key_id=api_key_id,
        environment=command.environment,
        client_id=int(command.client_id),
    )
