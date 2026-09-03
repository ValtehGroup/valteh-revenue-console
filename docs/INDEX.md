# Project context index

Use this page as a router, not as a reading list. Start with the row matching the task, then inspect the linked code and tests.

| Task | Load first | Primary code |
| --- | --- | --- |
| Understand the system | [Architecture overview](architecture/overview.md), [module map](architecture/modules.md) | `app/main.py`, `app/routes.py` |
| Pricing, revenue, margins, break-even | [Business rules](domain/business-rules.md), [invariants](domain/invariants.md), [terminology](domain/terminology.md) | `app/domain/`, relevant domain tests |
| Clients, costs, subscriptions, usage | [Data model](data/data-model.md), [database](data/database.md) | `app/data/schemas.py`, repositories, migrations |
| SAREMI pricing or usage | [SAREMI](integrations/saremi.md), [usage-event ingestion](integrations/saremi-usage-events.md), [business rules](domain/business-rules.md) | Pricing/revenue domain, provider adapter, SAREMI tests and migrations |
| Operational-event schema or ingestion | [Event flow](architecture/data-flow.md) | `app/domain/operational_events.py`, operational repositories and tests |
| Anthropic usage/cost | [Anthropic](integrations/anthropic.md) | Admin adapter, sync/allocation domain, history repositories |
| FX or scenarios | [Integration overview](integrations/overview.md), [business rules](domain/business-rules.md) | Banxico adapter, FX domain/repository, scenario domain |
| Setup, tests, troubleshooting | [Development index](development/README.md) | `pyproject.toml`, `README.md`, tests |
| Schema change | [Migrations](data/migrations.md), [data model](data/data-model.md) | `migrations/versions/`, `app/data/schemas.py` |
| Why a boundary exists | [Decision index](decisions/INDEX.md) | ADRs and cited tests |

## Documentation map

- `architecture/`: system shape, module ownership, runtime flows, dependencies.
- `domain/`: terminology, financial rules, and invariants.
- `data/`: persistence model, lifecycle, and migrations.
- `integrations/`: provider boundaries and current maturity.
- `development/`: setup, validation, conventions, and debugging.
- `decisions/`: durable architecture decisions.

Detailed operator/user documents already in `docs/` remain authoritative for their narrow subjects and are linked from the relevant modular pages.

Keep this index limited to implemented behavior and accepted architectural boundaries. Add roadmap material only when it represents approved, active work in this repository.
