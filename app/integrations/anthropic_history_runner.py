from __future__ import annotations

import argparse
from datetime import date

from app.config import get_settings
from app.data.anthropic_history_repository import AnthropicHistoryRepository
from app.domain.anthropic_history_sync import (
    SYNC_MODES,
    AnthropicHistorySyncService,
    AnthropicSyncRequest,
    safe_sync_error_message,
)
from app.integrations.anthropic_admin_api import AnthropicAdminClient


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "sync":
        parser.error("A command is required.")

    settings = get_settings()
    if settings.anthropic_admin_key is None:
        parser.error("ANTHROPIC_ADMIN_KEY is not configured in the server environment.")

    request = AnthropicSyncRequest(
        mode=args.mode,
        start_date=_date_argument(args.start_date),
        end_date=_date_argument(args.end_date),
        month=args.month,
        overlap_days=(args.overlap_days if args.overlap_days is not None else settings.anthropic_history_overlap_days),
        dry_run=args.dry_run,
    )
    service = AnthropicHistorySyncService(
        AnthropicAdminClient(settings.anthropic_admin_key.get_secret_value()),
        AnthropicHistoryRepository(),
    )
    try:
        result = service.sync(request)
    except Exception as exc:
        parser.exit(1, f"Anthropic history sync failed: {safe_sync_error_message(exc)}\n")

    prefix = "Dry run validated" if result.dry_run else "Historical sync completed"
    print(f"{prefix}: {result.starting_at.isoformat()} through {result.ending_at.isoformat()} UTC")
    print(f"API windows: {len(result.windows)}")
    print(f"Usage rows: {len(result.report.messages_usage_rows):,}")
    print(f"Total tokens: {result.report.total_api_tokens:,}")
    print(f"Cost rows: {len(result.report.cost_rows):,}")
    print(f"Billed cost: ${result.report.billed_organization_cost_usd:,.6f} USD")
    if result.persisted:
        print(
            "Usage writes: " f"{result.persisted.usage.inserted:,} inserted, {result.persisted.usage.updated:,} updated"
        )
        print("Cost writes: " f"{result.persisted.cost.inserted:,} inserted, {result.persisted.cost.updated:,} updated")
        print("Watermarks: usage=" f"{result.persisted.watermarks.usage}, cost={result.persisted.watermarks.cost}")
        print(f"Sync run: {result.persisted.run_id}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anthropic-history")
    subparsers = parser.add_subparsers(dest="command")
    sync = subparsers.add_parser("sync", help="Synchronize durable Anthropic usage and billed-cost facts.")
    sync.add_argument("--start-date", help="Inclusive UTC date in YYYY-MM-DD format.")
    sync.add_argument("--end-date", help="Inclusive UTC date in YYYY-MM-DD format.")
    sync.add_argument("--month", help="Calendar month in YYYY-MM format.")
    sync.add_argument("--overlap-days", type=int, help="Number of already-persisted days to refresh.")
    sync.add_argument("--dry-run", action="store_true", help="Fetch and validate without database writes.")
    sync.add_argument("--mode", choices=sorted(SYNC_MODES), default="incremental")
    return parser


def _date_argument(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid date '{value}'; expected YYYY-MM-DD.") from exc


if __name__ == "__main__":
    raise SystemExit(main())
