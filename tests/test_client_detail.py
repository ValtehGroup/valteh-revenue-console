from app.data.repositories import SeedRepository
from app.pages.client_detail import _client_detail_content, _default_client_id


def test_client_detail_uses_latest_client_active_month_when_global_latest_month_is_later(monkeypatch) -> None:
    monkeypatch.setattr("app.data.repositories.current_month_key", lambda: "2026-07")

    content = _client_detail_content(1)

    assert content is not None


def test_client_detail_defaults_to_client_active_in_latest_month(monkeypatch) -> None:
    monkeypatch.setattr("app.data.repositories.current_month_key", lambda: "2026-07")
    repo = SeedRepository()

    assert _default_client_id(repo, repo.clients()) == 1
