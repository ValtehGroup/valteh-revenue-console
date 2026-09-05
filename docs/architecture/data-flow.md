# Data flows

## Startup and normal reads

1. `app.main.create_app()` calls `app.data.seed_data.seed_database()`.
2. Alembic upgrades the configured database to head.
3. Reference CSVs populate only empty tables; later edits remain in SQL.
4. Pages query repositories, which construct domain models and calculated presentations.
5. Dash renders results and handles unavailable/not-applicable states.

## Operational usage

```text
source products -> valteh-revenue-api -> normalized SQL usage_events
                                              |
                                              v
Revenue Console repositories -> domain revenue/cost rules -> dashboard
```

Source facts exclude price, cost, margin, and invoice fields. The console resolves `(source_system, external_client_reference)` to durable client IDs, deduplicates imported facts, and applies date-effective subscriptions and costs.

Only when changing the shared event schema or ingestion pipeline, also load the detailed [event contract](../shared-operational-event-contract.md) and [consumption architecture](../event-consumption-architecture.md). They are unnecessary for normal dashboard, pricing, or reporting work.

## Anthropic

Historical sync explicitly fetches completed UTC days, validates provider facts, and persists idempotently with independent watermarks. Live reports are session-only and never enter history. Cost allocation is derived from immutable provider facts; unmatched cost stays explicit.

## FX

Before mounting a page, the route checks the latest persisted Banxico USD/MXN FIX observation. It reads locally and
contacts Banxico only when no observation exists or the latest is more than seven calendar days old. A process-wide
lock prevents concurrent stale requests from duplicating the provider call. The Scenarios page also retains its manual
refresh control. Dated valuation uses the exact or latest prior valid rate and does not rewrite original source amounts.
If refresh fails, the latest observation is carried forward so pages remain available, while a visible warning names
its date and offers the manual retry. No synthetic current-date observation is persisted.
