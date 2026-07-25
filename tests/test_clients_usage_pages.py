from app.data.repositories import SeedRepository
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


def test_usage_rows_include_client_id_and_name() -> None:
    rows = _usage_rows(SeedRepository())

    assert rows
    assert rows[0]["client_id"] == 1
    assert rows[0]["client_name"] == "Notaria 38 Queretaro, Qro."


def test_clicked_client_row_id_selects_client_detail() -> None:
    assert _client_id_from_active_cell({"row": 1, "column": 2, "row_id": 2}) == 2


def test_inactive_client_detail_renders_without_active_plan() -> None:
    assert _client_detail_content(2) is not None
