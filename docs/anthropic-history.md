# Anthropic History Operations

## Responsibilities and safety boundary

The integration has two deliberately separate paths:

- **Live Admin API report:** the Usage page queries Anthropic for a report of at most 31 days. The latest
  successful result is cached in browser session storage so navigation does not discard it. It never writes
  historical facts, sync runs, watermarks, or the Admin API secret.
- **Historical database report:** the **Historical** subtab reads and displays the complete persisted history.
  Opening the page or switching tabs never calls Anthropic or writes provider facts.
- **History synchronization:** the explicit **Update history** button and the `anthropic-history sync` CLI call
  the same idempotent synchronization service. The CLI remains the entry point for scheduled operations; no sync
  is started by Gunicorn, page loads, tab changes, or application startup.

The Admin API secret remains an environment secret. It is not stored in these tables, command output, audit
errors, or browser state.

## Stored facts

`anthropic_usage_daily` stores daily message usage at the provider grain:

```text
bucket date + API key ID + workspace ID + model + service tier
```

`anthropic_cost_daily` stores original billed lines before allocation:

```text
bucket date + workspace ID + description + model + cost type + token type + currency
```

Database `UNIQUE` constraints enforce both identities. Synchronization uses UPSERT, replacing provider values
rather than adding them. It also removes obsolete rows inside the explicitly refreshed range, so a provider
correction that removes a line is mirrored correctly. Repeating or overlapping a range is idempotent.

API-key metadata and workspace names are reference data. `anthropic_api_key_assignments` keeps date-effective
client/environment ownership. Raw provider costs remain separate from the dashboard's derived allocation.

`anthropic_sync_watermarks` has independent `usage` and `cost` completion dates. A date advances only in the same
transaction that validates and commits the corresponding facts. `anthropic_sync_runs` records successful and
failed attempts without secrets.

## Initial July 2026 bootstrap

Back up the production database before the first migration and import. The migration creates schema only; it
does not call Anthropic or backfill facts.

```bash
alembic upgrade head
anthropic-history sync --mode bootstrap --start-date 2026-07-01 --end-date 2026-08-26 --dry-run
anthropic-history sync --mode bootstrap --start-date 2026-07-01 --end-date 2026-08-26
```

Replace `2026-08-26` with yesterday's UTC date when executing the bootstrap. Omitting both explicit dates in
bootstrap mode automatically uses `2026-07-01` through yesterday UTC:

```bash
anthropic-history sync --mode bootstrap --dry-run
anthropic-history sync --mode bootstrap
```

The runner automatically divides the range into inclusive windows of at most 31 days. Inspect row counts, total
tokens, billed USD, and resulting watermarks. Then open the Usage page and select **Historical** to verify the
complete persisted history.

If the installed console script is unavailable, use the equivalent module command:

```bash
python -m app.integrations.anthropic_history_runner sync --mode bootstrap --dry-run
```

## Incremental and monthly operation

After bootstrap, the ordinary command calculates the range from the earliest successful watermark through
yesterday UTC. It refreshes seven already-persisted days by default to capture delayed corrections.

```bash
anthropic-history sync
```

Configure the overlap with `ANTHROPIC_HISTORY_OVERLAP_DAYS` or override one run:

```bash
anthropic-history sync --overlap-days 10
```

Schedule that deterministic command externally, for example at 04:00 UTC on the second day of every month. The
web process must not contain an in-process scheduler. The current UTC day is always rejected because it may be
incomplete.

An authorized dashboard user may instead select **Update history** in the **Historical** subtab. That action is
never automatic: it performs the same incremental sync, refreshes the configured overlap, advances watermarks
only after a validated transaction, and then reloads the full persisted report. Repeated clicks do not add the
same costs or usage twice because provider identities are protected by database uniqueness and UPSERT.

## Dry runs and repairs

A dry run performs provider requests and validation but writes no facts, metadata, sync runs, or watermarks:

```bash
anthropic-history sync --month 2026-07 --mode repair --dry-run
```

After reviewing the output, refresh an old month idempotently:

```bash
anthropic-history sync --month 2026-07 --mode repair
```

Repair runs cannot move a watermark backward. Explicit start and end dates are also supported, but both are
required together.

## Reconciliation and failures

Before commit, synchronization verifies that provider identities are unique, every row belongs to the requested
UTC range, persisted row counts and totals match the refreshed provider response, and allocated plus unallocated
cost reconciles to billed cost using exact decimal arithmetic.

On failure, fact changes roll back and watermarks remain unchanged. A separate sanitized failed-run audit row is
written when possible. Diagnose failures by checking the latest `anthropic_sync_runs` row, server connectivity,
Admin API permissions, requested dates, and database health. Never print the API secret or authorization headers.
Rerun the same command after correction; UPSERT and range reconciliation make retries safe.

Database backup and restore follow the normal policy for the configured `DATABASE_URL`. Restore the database as
a unit so facts, watermarks, assignment periods, and audit records remain consistent.
