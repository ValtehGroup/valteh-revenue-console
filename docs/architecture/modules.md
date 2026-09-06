# Module responsibilities

| Path | Responsibility | Must not own |
| --- | --- | --- |
| `app/pages/` | Dash layouts, callbacks, presentation-state handling | Canonical financial formulas or provider parsing |
| `app/components/` | Reusable UI primitives and chart styling | Business rules or persistence |
| `app/domain/` | Provider-independent models, calculations, validation, sync orchestration | Dash components, SQLAlchemy sessions, credentials |
| `app/data/` | ORM schemas, repositories, transactions, migrations interface, idempotent seed import | Provider HTTP details or presentation formatting |
| `app/integrations/` | Anthropic/Banxico clients and current mock source adapters | Commercial decisions or UI behavior |
| `migrations/` | Ordered schema and controlled data evolution | Runtime-only shortcuts |
| `data/` | Initial reference CSVs | Live editing or secret storage |
| `tests/` | Regression evidence across domain, repositories, migrations, and UI structure | Production state |

## High-value entry points

- Application: `app/main.py`, `app/routes.py`, `app/layout.py`.
- Aggregate read model: `app/data/repositories.py::SeedRepository` (historical name; it reads both SQL runtime data and seed inputs).
- Commercial domain: `pricing_engine.py`, `pricing_simulator.py`, `revenue_engine.py`, `unit_economics.py`.
- Cost/FX domain: `cost_engine.py`, `fx_rates.py`, `fx_history_sync.py`, `display_currency.py`.
- Anthropic: `anthropic_admin_api.py`, `anthropic_history_sync.py`, `anthropic_cost_allocation.py`, matching repositories.
- Client and cost administration: `client_repository.py`, `cost_repository.py`.

When a page contains an important calculation, first look for an existing domain function or repository projection. Extract a rule only when it creates a real boundary or testable reuse.


## Dashboard chart presentation

Executive Summary uses AG Grid Community for its two five-client rankings. Amounts remain in MXN regardless of the display-currency selector, explicitly labelled beside the tables. Numeric values drive sorting and filtering; presentation formats money to two decimals and fractional margins as percentages.

`app/components/chart_shell.py` owns the shared Plotly shell used by Executive Summary, Usage, Client Detail, Costs, Pricing, Scenarios, and FX history. It gives each responsive graph an explicit `height` and `minHeight`, applies the common modebar configuration, attaches a `dcc.Tooltip`, and derives a keyboard/touch-accessible “View exact values” disclosure from the figure.

Each point stores safe display metadata in `customdata` as `[title, context, metric, formatted_value]`. Native Plotly hover is disabled; `app/assets/chart-shell.js` renders the metadata clientside and clears stale tooltip content when a figure changes. Time-series traces use the series as the title and the period as context. Values retain exact units or currency in their formatted field.

`app/components/chart_theme.py` is the source of chart typography, axes, grid, background, and color palettes. Callback-generated figures receive `theme-store` explicitly. Semantic service and scenario labels use stable palette slots; other dynamic categories use a deterministic hash so their colors do not depend on row order.
