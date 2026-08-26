import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.integrations.anthropic_admin_api import AnthropicAdminClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse(io.BytesIO):
    def __init__(self, payload: dict):
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_client_loads_claude_code_usage_and_cost_without_exposing_key_in_url() -> None:
    responses = [
        FakeResponse(
            {
                "data": [
                    {
                        "actor": {"email_address": "developer@example.com", "type": "user_actor"},
                        "core_metrics": {"num_sessions": 3},
                        "customer_type": "api",
                        "date": "2026-08-25T00:00:00Z",
                        "terminal_type": "terminal",
                        "model_breakdown": [
                            {
                                "estimated_cost": {"amount": 186, "currency": "USD"},
                                "model": "claude-sonnet",
                                "tokens": {
                                    "input": 100,
                                    "output": 20,
                                    "cache_creation": 10,
                                    "cache_read": 50,
                                },
                            }
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            }
        ),
        FakeResponse(
            {
                "data": [
                    {
                        "starting_at": "2026-08-25T00:00:00Z",
                        "ending_at": "2026-08-26T00:00:00Z",
                        "results": [
                            {
                                "api_key_id": "apikey_123",
                                "workspace_id": "wrkspc_123",
                                "model": "claude-sonnet",
                                "service_tier": "standard",
                                "uncached_input_tokens": 100,
                                "cache_creation": {
                                    "ephemeral_1h_input_tokens": 30,
                                    "ephemeral_5m_input_tokens": 10,
                                },
                                "cache_read_input_tokens": 50,
                                "output_tokens": 20,
                            }
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            }
        ),
        FakeResponse(
            {
                "data": [
                    {
                        "starting_at": "2026-08-25T00:00:00Z",
                        "ending_at": "2026-08-26T00:00:00Z",
                        "results": [
                            {
                                "amount": "123.45",
                                "currency": "USD",
                                "cost_type": "tokens",
                                "description": "Claude usage",
                                "model": "claude-sonnet",
                                "token_type": "uncached_input_tokens",
                                "workspace_id": "wrkspc_123",
                            }
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            }
        ),
        FakeResponse(
            {
                "data": [
                    {
                        "id": "apikey_123",
                        "name": "production-api-key",
                        "status": "active",
                        "workspace_id": "wrkspc_123",
                        "partial_key_hint": "sk-ant-...1234",
                    }
                ],
                "has_more": False,
                "last_id": "apikey_123",
            }
        ),
        FakeResponse(
            {
                "data": [{"id": "wrkspc_123", "name": "Default workspace"}],
                "has_more": False,
                "last_id": "wrkspc_123",
            }
        ),
    ]
    requests = []

    def opener(request, _timeout):
        requests.append(request)
        return responses.pop(0)

    report = AnthropicAdminClient("super-secret-admin-key", opener=opener).fetch_report(
        date(2026, 8, 25),
        date(2026, 8, 25),
    )

    assert report.total_sessions == 3
    assert report.total_tokens == 180
    assert report.total_api_tokens == 210
    assert report.estimated_claude_code_cost_usd == Decimal("1.86")
    assert report.billed_organization_cost_usd == Decimal("1.2345")
    assert report.usage_rows[0].actor == "developer@example.com"
    assert report.messages_usage_rows[0].api_key_id == "apikey_123"
    assert report.messages_usage_rows[0].cache_creation_tokens == 40
    assert report.messages_usage_rows[0].cache_creation_1h_tokens == 30
    assert report.messages_usage_rows[0].cache_creation_5m_tokens == 10
    assert report.cost_rows[0].workspace_id == "wrkspc_123"
    assert report.cost_rows[0].token_type == "uncached_input_tokens"
    assert report.api_keys[0].name == "production-api-key"
    assert report.workspaces[0].name == "Default workspace"
    assert all("super-secret-admin-key" not in request.full_url for request in requests)
    assert all(request.get_header("X-api-key") == "super-secret-admin-key" for request in requests)
    assert all(request.get_header("Anthropic-version") == "2023-06-01" for request in requests)


def test_client_rejects_ranges_longer_than_31_days_before_calling_api() -> None:
    client = AnthropicAdminClient("secret", opener=lambda *_args: pytest.fail("network should not be called"))

    with pytest.raises(ValueError, match="31 days"):
        client.fetch_report(date(2026, 7, 1), date(2026, 8, 1))


def test_anthropic_admin_key_is_redacted_by_settings() -> None:
    settings = Settings(_env_file=None, anthropic_admin_key="super-secret-admin-key")

    assert settings.anthropic_admin_key is not None
    assert settings.anthropic_admin_key.get_secret_value() == "super-secret-admin-key"
    assert "super-secret-admin-key" not in repr(settings)


def test_local_secret_file_and_docker_context_are_protected() -> None:
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")

    assert ".env" in gitignore.splitlines()
    assert ".env" in dockerignore.splitlines()
    assert "ANTHROPIC_ADMIN_KEY=" in env_example
    assert "sk-ant-" not in env_example
