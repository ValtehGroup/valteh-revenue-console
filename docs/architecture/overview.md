# Architecture overview

Valteh Revenue Console is an internal management-accounting dashboard for revenue, pricing, usage, costs, clients, margins, and scenarios across SAREMI, Graphos, Blockchain/BaaS, and SIGEN. Revenue events represent calculated commercial recognition, not invoices or collected cash.

## Runtime shape

```text
Dash pages and components
        |
        v
repositories / application orchestration
        |
        +--> domain calculations and validation
        +--> SQLAlchemy persistence
        +--> focused provider adapters
```

`app/main.py` creates the Dash app, runs database migration/seeding through `seed_database()`, builds the shell, and registers routes/callbacks. `app/routes.py` selects page layouts. The configured SQL database is the durable state; CSVs in `data/` seed empty tables only.

## Sources of truth

1. Code and tests define runtime behavior.
2. Alembic defines schema evolution.
3. Modular docs explain intent, boundaries, and operating rules.
4. Generated docs are navigation aids only.

## Architectural direction

Operational source systems emit facts. The separate `valteh-revenue-api` owns ingestion and normalization; this console reads normalized usage and applies commercial and economic rules. External providers remain behind focused adapters. New work should preserve these boundaries rather than placing ingestion, billing rules, or provider parsing in UI callbacks.

See [modules](modules.md), [data flow](data-flow.md), and [dependencies](dependencies.md).

