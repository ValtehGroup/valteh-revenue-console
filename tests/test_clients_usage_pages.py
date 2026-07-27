from datetime import UTC, date, datetime
from decimal import Decimal

from app.data.repositories import SeedRepository
from app.domain.models import Client, ClientProfitability, UsageEvent
from app.pages.client_detail import _client_detail_content
from app.pages.clients import _client_id_from_active_cell, _client_rows
from app.pages.usage import _usage_rows


def test_clients_table_includes_active_and_inactive_clients() -> None:
    rows = _client_rows(SeedRepository(), "2026-07")

    assert len(rows) == 3
    assert [row["id"] for row in rows] == [1, 2, 3]
    assert {row["status"] for row in rows} == {"active", "inactive"}
    assert [row["client_name"] for row in rows if row["status"] == "active"] == ["Notaria 38 Queretaro, Qro."]
    assert all(row["alerts"] == "Inactive" for row in rows if row["status"] == "inactive")


def test_client_lifecycle_dates_follow_status_and_active_services_are_hidden() -> None:
    row = _client_rows(SeedRepository(), "2026-07")[0]
    columns = list(row)

    status_index = columns.index("client_status")
    assert columns[status_index + 1 : status_index + 3] == ["start_date", "end_date"]
    assert "active_services" not in columns


def test_usage_rows_include_client_id_and_name() -> None:
    rows = _usage_rows(SeedRepository())

    assert rows
    assert rows[0]["client_id"] == 2
    assert rows[0]["client_code"] == "test_0002"
    assert rows[0]["client_name"] == "(test) Notaria X Queretaro, Qro."
    assert rows[0]["resolution_status"] == "Resolved"


def test_clicked_client_row_id_selects_client_detail() -> None:
    assert _client_id_from_active_cell({"row": 1, "column": 2, "row_id": 2}) == 2


def test_inactive_client_detail_renders_without_active_plan() -> None:
    assert _client_detail_content(2) is not None


def test_active_client_without_subscription_is_not_labeled_inactive() -> None:
    client = Client(
        id=10,
        client_code="client_0010",
        name="New client",
        client_type="notary",
        status="active",
        start_date=date(2026, 7, 1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Repo:
        def clients(self):
            return [client]

        def active_clients(self, month):
            return [client]

        def monthly_summary(self, month):
            return {"fixed_cost": Decimal("0")}

        def usage_for_client_month(self, client_id, month):
            return []

        def client_profitability(self, client_id, month):
            return ClientProfitability(
                client_id=client_id,
                revenue=Decimal("0"),
                variable_cost=Decimal("0"),
                gross_margin=Decimal("0"),
                gross_margin_percentage=Decimal("0"),
            )

        def active_plan_for_client_month(self, client_id, month):
            return None

    row = _client_rows(Repo(), "2026-07")[0]

    assert row["client_status"] == "active"
    assert row["pricing_plan"] == "No active plan"
    assert "active_services" not in row
    assert row["alerts"] == "No active plan"


def test_usage_name_is_resolved_at_read_time() -> None:
    event = UsageEvent(
        id=1,
        client_id=10,
        service_code="saremi",
        event_type="saremi.document_validation",
        quantity=Decimal("1"),
        unit="document",
        event_timestamp=datetime(2026, 7, 1),
        source_system="saremi",
    )
    client = Client(
        id=10,
        client_code="client_0010",
        name="Renamed client",
        client_type="notary",
        status="active",
        start_date=date(2026, 7, 1),
    )

    class Repo:
        def clients(self):
            return [client]

        def usage_events(self):
            return [event]

    class References:
        def list_references(self, client_id, include_inactive=False):
            return []

    assert _usage_rows(Repo(), References())[0]["client_name"] == "Renamed client"
