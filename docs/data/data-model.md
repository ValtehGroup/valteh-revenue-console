# Data model

`app/data/schemas.py` contains SQLAlchemy tables; `app/domain/models.py` contains the principal validated domain models.

## Commercial and operating records

- `clients` and `client_external_references`: durable identity plus source-scoped mappings.
- `pricing_plans` and `client_subscriptions`: versioned catalog and date-effective contract snapshots.
- `usage_events` and `revenue_events`: normalized operational facts and calculated management revenue.
- `cost_items`: versioned actual/budget/estimate cost records with entered and normalized currency fields.
- `services` and `scenario_assumptions`: reference data.

## Operational ingestion support

- `imported_operational_events`: source provenance and deduplication.
- `event_classifications`: economic classification owned downstream of source facts.
- `event_import_cursors`: incremental source position.

## Provider history

- `usd_mxn_rates`: dated Banxico FIX observations.
- `anthropic_usage_daily`, `anthropic_cost_daily`: normalized immutable provider facts.
- `anthropic_api_keys`, `anthropic_workspaces`: provider metadata.
- `anthropic_api_key_assignments`: date-effective ownership.
- `anthropic_sync_watermarks`, `anthropic_sync_runs`: sync state and audit trail.

Use domain models at business boundaries and ORM models inside repositories. Never persist credentials or raw provider secrets in these records.

