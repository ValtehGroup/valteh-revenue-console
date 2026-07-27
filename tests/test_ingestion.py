from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data.schemas import Base, EventImportCursorORM, ImportedOperationalEventORM
from app.domain.operational_events import (
    OperationalEvent,
    OperationalEventPage,
    OperationalEventPagination,
)
from app.integrations.ingestion import sync_source


def _make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _event(event_id: str, occurred_at: datetime) -> OperationalEvent:
    return OperationalEvent(
        id=event_id,
        source_system="baas-qro",
        event_type="blockchain.document_anchored",
        event_category="blockchain",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        status="succeeded",
        correlation_id=f"corr-{event_id}",
        document_hash="sha256:abc",
        quantity=1,
        unit="document",
    )


class FakeSource:
    """In-memory source returning preconfigured pages keyed by cursor."""

    source_system = "baas-qro"

    def __init__(self, pages: dict[str | None, OperationalEventPage]) -> None:
        self.pages = pages
        self.calls: list[str | None] = []

    def fetch_page(self, cursor, limit):  # noqa: ANN001 - matches Protocol
        self.calls.append(cursor)
        return self.pages[cursor]


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(ImportedOperationalEventORM)).scalar_one()


def test_single_page_imports_all_events() -> None:
    session = _make_session()
    source = FakeSource(
        {
            None: OperationalEventPage(
                data=[_event("e1", datetime(2026, 5, 1)), _event("e2", datetime(2026, 5, 2))],
                pagination=OperationalEventPagination(next_cursor=None, has_more=False),
            )
        }
    )

    result = sync_source(session, source)

    assert result.imported == 2
    assert result.skipped == 0
    assert _count(session) == 2
    assert result.last_occurred_at == datetime(2026, 5, 2)


def test_dedup_skips_already_imported_events() -> None:
    session = _make_session()
    page = OperationalEventPage(
        data=[_event("e1", datetime(2026, 5, 1)), _event("e2", datetime(2026, 5, 2))],
        pagination=OperationalEventPagination(next_cursor=None, has_more=False),
    )
    # Two independent runs returning the same page.
    first = sync_source(session, FakeSource({None: page}))
    assert first.imported == 2

    second = sync_source(session, FakeSource({None: page}))
    assert second.imported == 0
    assert second.skipped == 2
    assert _count(session) == 2


def test_dedup_within_a_single_page() -> None:
    session = _make_session()
    source = FakeSource(
        {
            None: OperationalEventPage(
                data=[_event("dup", datetime(2026, 5, 1)), _event("dup", datetime(2026, 5, 1))],
                pagination=OperationalEventPagination(has_more=False),
            )
        }
    )

    result = sync_source(session, source)

    assert result.imported == 1
    assert result.skipped == 1
    assert _count(session) == 1


def test_cursor_paginates_through_multiple_pages() -> None:
    session = _make_session()
    source = FakeSource(
        {
            None: OperationalEventPage(
                data=[_event("e1", datetime(2026, 5, 1))],
                pagination=OperationalEventPagination(next_cursor="c2", has_more=True),
            ),
            "c2": OperationalEventPage(
                data=[_event("e2", datetime(2026, 5, 2))],
                pagination=OperationalEventPagination(next_cursor="c3", has_more=True),
            ),
            "c3": OperationalEventPage(
                data=[_event("e3", datetime(2026, 5, 3))],
                pagination=OperationalEventPagination(next_cursor=None, has_more=False),
            ),
        }
    )

    result = sync_source(session, source)

    assert result.imported == 3
    assert result.pages == 3
    assert source.calls == [None, "c2", "c3"]
    cursor_row = session.get(EventImportCursorORM, "baas-qro")
    assert cursor_row.status == "ok"
    assert cursor_row.last_occurred_at == datetime(2026, 5, 3)


def test_resume_from_stored_cursor() -> None:
    session = _make_session()
    # Seed a cursor as if a previous run stopped at "c2".
    session.add(EventImportCursorORM(source_system="baas-qro", cursor="c2"))
    session.commit()

    source = FakeSource(
        {
            "c2": OperationalEventPage(
                data=[_event("e2", datetime(2026, 5, 2))],
                pagination=OperationalEventPagination(next_cursor=None, has_more=False),
            )
        }
    )

    result = sync_source(session, source)

    assert source.calls == ["c2"]
    assert result.imported == 1


def test_sync_error_is_recorded_on_cursor() -> None:
    session = _make_session()

    class BrokenSource:
        source_system = "baas-qro"

        def fetch_page(self, cursor, limit):  # noqa: ANN001
            raise RuntimeError("source down")

    result = sync_source(session, BrokenSource())

    assert result.error == "source down"
    cursor_row = session.get(EventImportCursorORM, "baas-qro")
    assert cursor_row.status == "error"
    assert cursor_row.error_message == "source down"


def test_unknown_client_reference_is_retained_as_raw_event() -> None:
    session = _make_session()
    event = _event("unresolved", datetime(2026, 5, 1)).model_copy(
        update={"client_reference": "unknown-tenant"}
    )
    source = FakeSource(
        {
            None: OperationalEventPage(
                data=[event],
                pagination=OperationalEventPagination(has_more=False),
            )
        }
    )

    result = sync_source(session, source)
    stored = session.scalar(
        select(ImportedOperationalEventORM).where(
            ImportedOperationalEventORM.source_event_id == "unresolved"
        )
    )

    assert result.imported == 1
    assert stored.source_client_ref == "unknown-tenant"
    assert stored.raw_payload_json is not None
