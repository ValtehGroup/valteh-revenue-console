from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ANTHROPIC_API_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
MAX_REPORT_DAYS = 31
MAX_PAGES_PER_REQUEST = 100


class AnthropicAdminAPIError(RuntimeError):
    """Safe, user-facing error raised when an Anthropic report cannot be loaded."""


@dataclass(frozen=True)
class ClaudeCodeUsageRow:
    date: str
    actor: str
    actor_type: str
    customer_type: str
    terminal_type: str
    models: str
    sessions: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: Decimal

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens + self.cache_read_tokens


@dataclass(frozen=True)
class MessagesUsageRow:
    date: str
    api_key_id: str
    workspace_id: str
    model: str
    service_tier: str
    uncached_input_tokens: int
    cache_creation_1h_tokens: int
    cache_creation_5m_tokens: int
    cache_read_tokens: int
    output_tokens: int
    web_search_requests: int

    @property
    def cache_creation_tokens(self) -> int:
        return self.cache_creation_1h_tokens + self.cache_creation_5m_tokens

    @property
    def total_tokens(self) -> int:
        return self.uncached_input_tokens + self.cache_creation_tokens + self.cache_read_tokens + self.output_tokens


@dataclass(frozen=True)
class AnthropicCostRow:
    date: str
    workspace_id: str
    description: str
    model: str
    cost_type: str
    token_type: str
    amount_usd: Decimal


@dataclass(frozen=True)
class AnthropicAPIKeyMetadata:
    id: str
    name: str
    status: str
    workspace_id: str
    partial_key_hint: str


@dataclass(frozen=True)
class AnthropicWorkspaceMetadata:
    id: str
    name: str


@dataclass(frozen=True)
class AnthropicAdminReport:
    usage_rows: tuple[ClaudeCodeUsageRow, ...]
    messages_usage_rows: tuple[MessagesUsageRow, ...]
    cost_rows: tuple[AnthropicCostRow, ...]
    api_keys: tuple[AnthropicAPIKeyMetadata, ...] = ()
    workspaces: tuple[AnthropicWorkspaceMetadata, ...] = ()

    @property
    def total_sessions(self) -> int:
        return sum(row.sessions for row in self.usage_rows)

    @property
    def total_tokens(self) -> int:
        return sum(row.total_tokens for row in self.usage_rows)

    @property
    def total_api_tokens(self) -> int:
        return sum(row.total_tokens for row in self.messages_usage_rows)

    @property
    def estimated_claude_code_cost_usd(self) -> Decimal:
        return sum((row.estimated_cost_usd for row in self.usage_rows), Decimal("0"))

    @property
    def billed_organization_cost_usd(self) -> Decimal:
        return sum((row.amount_usd for row in self.cost_rows), Decimal("0"))


def _open_url(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


class AnthropicAdminClient:
    """Small server-side client for Anthropic's Claude Code and Cost Admin APIs."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 20,
        opener: Callable[[Request, float], Any] | None = None,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("Anthropic Admin API key is required.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._opener = opener or _open_url

    def fetch_report(self, starting_at: date, ending_at: date) -> AnthropicAdminReport:
        """Return inclusive daily Claude Code usage and organization cost data."""

        _validate_date_range(starting_at, ending_at)
        usage_rows: list[ClaudeCodeUsageRow] = []
        report_date = starting_at
        while report_date <= ending_at:
            records = self._get_all_pages(
                "/v1/organizations/usage_report/claude_code",
                [("starting_at", report_date.isoformat()), ("limit", "1000")],
            )
            usage_rows.extend(_parse_usage_rows(records))
            report_date += timedelta(days=1)

        messages_usage_records = self._get_all_pages(
            "/v1/organizations/usage_report/messages",
            [
                ("starting_at", f"{starting_at.isoformat()}T00:00:00Z"),
                ("ending_at", f"{(ending_at + timedelta(days=1)).isoformat()}T00:00:00Z"),
                ("bucket_width", "1d"),
                ("group_by[]", "api_key_id"),
                ("group_by[]", "workspace_id"),
                ("group_by[]", "model"),
                ("group_by[]", "service_tier"),
                ("limit", str(MAX_REPORT_DAYS)),
            ],
        )
        cost_records = self._get_all_pages(
            "/v1/organizations/cost_report",
            [
                ("starting_at", f"{starting_at.isoformat()}T00:00:00Z"),
                ("ending_at", f"{(ending_at + timedelta(days=1)).isoformat()}T00:00:00Z"),
                ("bucket_width", "1d"),
                ("group_by[]", "description"),
                ("group_by[]", "workspace_id"),
                ("limit", str(MAX_REPORT_DAYS)),
            ],
        )
        api_key_records = self._get_cursor_collection("/v1/organizations/api_keys", [("limit", "1000")])
        workspace_records = self._get_cursor_collection(
            "/v1/organizations/workspaces",
            [("limit", "1000"), ("include_archived", "false")],
        )
        return AnthropicAdminReport(
            usage_rows=tuple(usage_rows),
            messages_usage_rows=tuple(_parse_messages_usage_rows(messages_usage_records)),
            cost_rows=tuple(_parse_cost_rows(cost_records)),
            api_keys=tuple(_parse_api_keys(api_key_records)),
            workspaces=tuple(_parse_workspaces(workspace_records)),
        )

    def _get_all_pages(self, path: str, query: Sequence[tuple[str, str]]) -> list[Mapping[str, Any]]:
        records: list[Mapping[str, Any]] = []
        page: str | None = None

        for _page_number in range(MAX_PAGES_PER_REQUEST):
            page_query = list(query)
            if page:
                page_query.append(("page", page))
            payload = self._get_json(path, page_query)
            data = payload.get("data")
            if not isinstance(data, list) or not all(isinstance(item, Mapping) for item in data):
                raise AnthropicAdminAPIError("Anthropic returned an invalid report response.")
            records.extend(data)

            if not payload.get("has_more"):
                return records
            next_page = payload.get("next_page")
            if not isinstance(next_page, str) or not next_page:
                raise AnthropicAdminAPIError("Anthropic returned an invalid pagination cursor.")
            page = next_page

        raise AnthropicAdminAPIError("Anthropic report exceeded the pagination safety limit.")

    def _get_cursor_collection(self, path: str, query: Sequence[tuple[str, str]]) -> list[Mapping[str, Any]]:
        records: list[Mapping[str, Any]] = []
        after_id: str | None = None

        for _page_number in range(MAX_PAGES_PER_REQUEST):
            page_query = list(query)
            if after_id:
                page_query.append(("after_id", after_id))
            payload = self._get_json(path, page_query)
            data = payload.get("data")
            if not isinstance(data, list) or not all(isinstance(item, Mapping) for item in data):
                raise AnthropicAdminAPIError("Anthropic returned an invalid collection response.")
            records.extend(data)

            if not payload.get("has_more"):
                return records
            last_id = payload.get("last_id")
            if not isinstance(last_id, str) or not last_id:
                raise AnthropicAdminAPIError("Anthropic returned an invalid collection cursor.")
            after_id = last_id

        raise AnthropicAdminAPIError("Anthropic collection exceeded the pagination safety limit.")

    def _get_json(self, path: str, query: Sequence[tuple[str, str]]) -> Mapping[str, Any]:
        url = f"{ANTHROPIC_API_BASE_URL}{path}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "accept": "application/json",
                "anthropic-version": ANTHROPIC_API_VERSION,
                "user-agent": "valteh-revenue-console/0.1.0",
                "x-api-key": self._api_key,
            },
            method="GET",
        )
        try:
            with self._opener(request, self._timeout_seconds) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise AnthropicAdminAPIError(_http_error_message(exc.code)) from exc
        except (TimeoutError, URLError) as exc:
            raise AnthropicAdminAPIError("Could not connect to the Anthropic Admin API.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise AnthropicAdminAPIError("Anthropic returned an unreadable report response.") from exc

        if not isinstance(payload, Mapping):
            raise AnthropicAdminAPIError("Anthropic returned an invalid report response.")
        return payload


def _validate_date_range(starting_at: date, ending_at: date) -> None:
    if ending_at < starting_at:
        raise ValueError("End date must be on or after start date.")
    number_of_days = (ending_at - starting_at).days + 1
    if number_of_days > MAX_REPORT_DAYS:
        raise ValueError(f"Report ranges are limited to {MAX_REPORT_DAYS} days.")


def _parse_usage_rows(records: Sequence[Mapping[str, Any]]) -> list[ClaudeCodeUsageRow]:
    rows: list[ClaudeCodeUsageRow] = []
    for record in records:
        actor = _mapping(record.get("actor"))
        core_metrics = _mapping(record.get("core_metrics"))
        model_breakdown = record.get("model_breakdown")
        if not isinstance(model_breakdown, list):
            model_breakdown = []

        model_names: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        estimated_cost_usd = Decimal("0")
        for breakdown in model_breakdown:
            model = _mapping(breakdown)
            tokens = _mapping(model.get("tokens"))
            estimated_cost = _mapping(model.get("estimated_cost"))
            model_name = str(model.get("model") or "Unknown model")
            model_names.append(model_name)
            input_tokens += _as_int(tokens.get("input"))
            output_tokens += _as_int(tokens.get("output"))
            cache_creation_tokens += _as_int(tokens.get("cache_creation"))
            cache_read_tokens += _as_int(tokens.get("cache_read"))
            estimated_cost_usd += _minor_units_to_major(estimated_cost.get("amount"))

        actor_name = actor.get("email_address") or actor.get("api_key_name") or "Unknown actor"
        rows.append(
            ClaudeCodeUsageRow(
                date=str(record.get("date") or "")[:10],
                actor=str(actor_name),
                actor_type=str(actor.get("type") or "unknown"),
                customer_type=str(record.get("customer_type") or "unknown"),
                terminal_type=str(record.get("terminal_type") or "unknown"),
                models=", ".join(sorted(set(model_names))) or "Unknown model",
                sessions=_as_int(core_metrics.get("num_sessions")),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                estimated_cost_usd=estimated_cost_usd,
            )
        )
    return rows


def _parse_messages_usage_rows(buckets: Sequence[Mapping[str, Any]]) -> list[MessagesUsageRow]:
    rows: list[MessagesUsageRow] = []
    for bucket in buckets:
        results = bucket.get("results")
        if not isinstance(results, list):
            continue
        bucket_date = str(bucket.get("starting_at") or "")[:10]
        for raw_result in results:
            result = _mapping(raw_result)
            cache_creation = _mapping(result.get("cache_creation"))
            server_tool_use = _mapping(result.get("server_tool_use"))
            rows.append(
                MessagesUsageRow(
                    date=bucket_date,
                    api_key_id=str(result.get("api_key_id") or "Not attributed"),
                    workspace_id=str(result.get("workspace_id") or "Default workspace"),
                    model=str(result.get("model") or "Not specified"),
                    service_tier=str(result.get("service_tier") or "unknown"),
                    uncached_input_tokens=_as_int(result.get("uncached_input_tokens")),
                    cache_creation_1h_tokens=_as_int(cache_creation.get("ephemeral_1h_input_tokens")),
                    cache_creation_5m_tokens=_as_int(cache_creation.get("ephemeral_5m_input_tokens")),
                    cache_read_tokens=_as_int(result.get("cache_read_input_tokens")),
                    output_tokens=_as_int(result.get("output_tokens")),
                    web_search_requests=_as_int(server_tool_use.get("web_search_requests")),
                )
            )
    return rows


def _parse_cost_rows(buckets: Sequence[Mapping[str, Any]]) -> list[AnthropicCostRow]:
    rows: list[AnthropicCostRow] = []
    for bucket in buckets:
        results = bucket.get("results")
        if not isinstance(results, list):
            continue
        bucket_date = str(bucket.get("starting_at") or "")[:10]
        for raw_result in results:
            result = _mapping(raw_result)
            rows.append(
                AnthropicCostRow(
                    date=bucket_date,
                    workspace_id=str(result.get("workspace_id") or "Default workspace"),
                    description=str(result.get("description") or "Unspecified cost"),
                    model=str(result.get("model") or "Not specified"),
                    cost_type=str(result.get("cost_type") or "unknown"),
                    token_type=str(result.get("token_type") or "unknown"),
                    amount_usd=_minor_units_to_major(result.get("amount")),
                )
            )
    return rows


def _parse_api_keys(records: Sequence[Mapping[str, Any]]) -> list[AnthropicAPIKeyMetadata]:
    return [
        AnthropicAPIKeyMetadata(
            id=str(record.get("id") or ""),
            name=str(record.get("name") or "Unnamed API key"),
            status=str(record.get("status") or "unknown"),
            workspace_id=str(record.get("workspace_id") or "Default workspace"),
            partial_key_hint=str(record.get("partial_key_hint") or ""),
        )
        for record in records
        if record.get("id")
    ]


def _parse_workspaces(records: Sequence[Mapping[str, Any]]) -> list[AnthropicWorkspaceMetadata]:
    return [
        AnthropicWorkspaceMetadata(
            id=str(record.get("id") or ""),
            name=str(record.get("name") or "Unnamed workspace"),
        )
        for record in records
        if record.get("id")
    ]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _minor_units_to_major(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)) / Decimal("100")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AnthropicAdminAPIError("Anthropic returned an invalid currency amount.") from exc


def _http_error_message(status_code: int) -> str:
    if status_code == 401:
        return "Anthropic rejected the Admin API key (HTTP 401)."
    if status_code == 403:
        return "The Admin API key is not allowed to read this Anthropic report (HTTP 403)."
    if status_code == 429:
        return "Anthropic rate-limited the report request. Please retry later (HTTP 429)."
    return f"Anthropic could not load the report (HTTP {status_code})."
