from dash import dash_table, html

from app.data.repositories import SeedRepository
from app.pages.client_detail import _client_detail_content, _default_client_id, _latest_client_month


def test_client_detail_uses_latest_client_active_month_when_global_latest_month_is_later(monkeypatch) -> None:
    monkeypatch.setattr("app.data.repositories.current_month_key", lambda: "2026-07")

    content = _client_detail_content(1)

    assert content is not None


def test_client_detail_defaults_to_client_active_in_latest_month(monkeypatch) -> None:
    monkeypatch.setattr("app.data.repositories.current_month_key", lambda: "2026-07")
    repo = SeedRepository()

    assert _default_client_id(repo, repo.clients()) == 1


def test_inactive_client_detail_uses_recorded_history() -> None:
    repo = SeedRepository()

    assert _latest_client_month(repo, 2, repo.available_months()) == "2026-06"
    assert len(repo.usage_history_for_client_month(2, "2026-06")) == 5
    assert repo.subscription_for_client_month(2, "2026-06") is not None
    assert _client_detail_content(2, "2026-06") is not None


def test_real_client_has_no_seeded_usage() -> None:
    repo = SeedRepository()

    assert all(event.client_id in {2, 3} for event in repo.usage_events())
    assert all(not repo.usage_history_for_client_month(1, month) for month in repo.available_months())


def test_event_sections_are_foldable_and_usage_is_not_limited_to_selected_period() -> None:
    content = _client_detail_content(2, "2026-07")
    descendants = list(_descendants(content))

    details = [component for component in descendants if isinstance(component, html.Details)]
    assert [section.children[0].children for section in details] == [
        "Usage Events",
        "Invoices / Revenue Events",
    ]
    usage_table = next(
        component
        for component in descendants
        if isinstance(component, dash_table.DataTable) and component.id == "client-usage-events"
    )
    assert len(usage_table.data) == 5


def _descendants(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _descendants(child)
    elif children is not None:
        yield from _descendants(children)
