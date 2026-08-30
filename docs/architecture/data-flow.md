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

An explicit user action fetches Banxico USD/MXN FIX observations. Reads use persisted history; rendering/startup never contacts Banxico. Dated valuation uses the exact or latest prior valid rate and does not rewrite original source amounts.
