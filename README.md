# Valteh Economics Dashboard

Internal economics, pricing, and business management dashboard for Valteh service lines:

- SAREMI document validation
- Graphos graph analytics
- Blockchain / BaaS property registry services
- SIGEN / Notarial Platform

The app tracks fixed costs, variable costs, usage, revenue, margins, pricing scenarios, and client-level profitability.

## Tech Stack

- Python 3.11+
- Dash
- Dash Bootstrap Components
- Plotly
- Pandas
- SQLAlchemy
- Pydantic
- SQLite locally, PostgreSQL-ready through `DATABASE_URL`
- Pytest
- Ruff and Black
- Docker and Docker Compose

## Install

```bash
cd Valteh_Revenue_App
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Run Locally

```bash
python -m app.main
```

or:

```bash
python app/main.py
```

Then open:

```text
http://localhost:8050
```

## Run Tests

```bash
pytest
```

## Format and Lint

```bash
black .
ruff check .
```

## Interface Themes

The interface supports light and dark themes without duplicating component styles. Semantic design
tokens live in `app/assets/00_tokens.css`; changing a shared color, border, radius, spacing value, or
shadow there updates the application consistently. Component rules live in `10_base.css` and
`20_components.css`, while responsive behavior lives in `30_responsive.css`.

The selector at the top of the sidebar applies `data-theme` to the document root. An explicit choice is
stored in browser `localStorage`; until a choice is made, the app follows the operating system's
`prefers-color-scheme` setting. `app/components/chart_theme.py` is the Python source of truth for initial
Plotly figures, and `app/assets/theme-init.js` updates visible and callback-generated charts when the
theme changes.

To modify a color, update the corresponding semantic token for light and dark mode in
`app/assets/00_tokens.css`, then keep the matching Plotly value in `app/components/chart_theme.py` and
`app/assets/theme-init.js` aligned. Page modules should consume semantic classes and the chart helper
instead of introducing new hardcoded theme colors.

## Run With Docker

```bash
copy .env.example .env
docker compose up --build
```

## Deploy

For Render or similar hosts, use the repository root as the project directory.

```text
Build command: pip install -e .
Start command: gunicorn app.main:server
```

The app also supports `python -m app.main` and reads the host-provided `PORT` environment variable.

## Dashboard User Guide

See [Costs and Clients User Guide](docs/dashboard-user-guide.md) for user-facing
instructions, column definitions, limitations, and worked examples.

## Seed Data

The app reads the current pilot seed data from five CSV files:

- `data/seed_clients.csv`
- `data/seed_client_subscriptions.csv`
- `data/seed_costs.csv`
- `data/seed_usage.csv`
- `data/seed_pricing_plans.csv`

Pilot assumptions are based on:

- Queretaro RPP request data from `solicitudes_RPP.xlsx`, which shows roughly 25.5k monthly state-level requests in the 2023 extract.
- Notary document-validation logic of roughly 2 people per registry matter and 6-8 documents per person.
- Current SAREMI pilot infrastructure cost: Hetzner CX41 at about $370 MXN/month plus Claude document analysis at about $0.95 MXN/document.
- Future-state blockchain/BaaS cost ranges from `modelo economico.pdf`, included as `estimate` rows (excluded from actuals) because the current pilot is focused on SAREMI, some Graphos visualization, and lightweight blockchain audit anchoring.
- Subscription history lives in `seed_client_subscriptions.csv`, so each client can start, stop, or switch plans over time. Setup, annual, monthly fixed, and variable usage fees live only in `seed_pricing_plans.csv`.

### Maintain cost history

`data/seed_costs.csv` is the initial reference catalog used to seed the economic dashboard. Runtime cost
management is stored in the SQL database configured by `DATABASE_URL`; the Dash app never rewrites the CSV.
The CSV stores actual, budget, and
estimate cost records for fixed subscriptions, one-time purchases, and usage-based rates. Each row is one
version of a cost. The numeric `id` identifies that specific row, while `cost_key` is the stable business
identifier for the underlying cost concept across versions.

When a cost changes, do not edit the historical amount in place:

1. Set `end_date` on the current row to the day before the change.
2. Add a row with a new unique `id`, the same `cost_key`, the new `start_date`, quantity, and unit cost.
3. Leave `end_date` empty while the new version remains in force.

For manual CSV edits, `id` can be left blank; the loader will assign the CSV row number as the record id.
`cost_key` can also be left blank for simple new costs, and the loader will derive one from stable descriptive
fields. For historical versions of the same cost, keep an explicit shared `cost_key` so the app can treat the
rows as versions of one concept.

Use `quantity` and `unit_cost` separately (for example, 4 users x 8 USD). `record_type=actual` participates in reported costs;
`budget` and `estimate` remain visible but are excluded from actual margins. Set `end_date` when a cost
ceases to exist. `enabled` is an operational kill switch and accepts values such as `TRUE/FALSE` or `ON/OFF`;
it should not replace lifecycle dates.

Costs are reported in MXN. Seed rows can currently be entered in `MXN` or `USD`; USD rows are converted to MXN
with the temporary flat rate `1 USD = 18 MXN`. Later FX history can replace this static conversion in the
currency utility without changing ordinary seed rows.

Effective dates are resolved for each requested accounting month. A row is active when `enabled=TRUE`,
`start_date` is on or before the requested period, and `end_date` is blank or still covers that period.
Overlapping `actual` rows for the same `cost_key` are rejected so a versioned cost cannot be double-counted.

Microsoft subscription example:

```csv
id,cost_key,quantity,unit_cost,currency,start_date,end_date
2,software.microsoft365.team,4,6,USD,2026-05-01,2026-06-30
15,software.microsoft365.team,4,8,USD,2026-07-01,
```

With this history, May 2026 and June 2026 use `4 x 6 USD x 18 = 432 MXN`. July 2026 onward uses
`4 x 8 USD x 18 = 576 MXN`. Historical months stay unchanged because the old row is ended instead of overwritten.

To add users to a per-user subscription, end the old row and add a new row with the same `cost_key`, updated
`quantity`, and the date the new user count starts. To add a new fixed cost, use `cost_type=fixed`,
`charge_basis=flat` or `per_user`, `billing_frequency=monthly`, and the appropriate `service_line`,
`provider`, and `category`. To add a usage-based cost, use `cost_type=variable`, `charge_basis=usage`,
`billing_frequency=usage`, and set `unit` to the usage event type that should consume the rate.
Use `cost_type=fixed` with `billing_frequency=once` for a one-time cost. Cost type describes whether
the amount varies with usage; billing frequency controls when it is recognized.

Usage-based costs are mapped by `unit`: for example, a cost row with `unit=saremi.document_validation` applies
to usage events whose `event_type` is `saremi.document_validation`. The same event type can have multiple
cost components with different `cost_key` values, such as an external AI rate plus local preprocessing.

To disable or end a cost, prefer setting `end_date` when the cost lifecycle is known. Use `enabled=FALSE`
only when the row should be excluded operationally without changing its historical dates.

The app imports costs only when the database cost catalog is empty and never overwrites later user changes.
Schema changes are managed with Alembic. The initialization helper is idempotent and can be run
with:

```bash
python -c "from app.data.seed_data import seed_database; seed_database()"
```

Run tests with:

```bash
pytest
```

The repository layer in `app/data/repositories.py` exposes this data to the UI and domain logic. `app/data/database.py` and `app/data/schemas.py` define the SQLAlchemy foundation for moving from CSV-backed local data to SQLite or PostgreSQL persistence.

## Client Management

`data/seed_clients.csv` initializes the client catalog only when the runtime
table is empty. After initialization, Clients are managed in SQL and CSV files
are not rewritten. Real-client public IDs use `client_0001`; designated test
clients use `test_0001`. Numeric primary keys remain internal for relationships
and calculations.

External product identifiers are mapped by `(source_system, client_reference)`.
API keys remain environment configuration and are never client identifiers.
Deactivation ends the client lifecycle and active subscriptions without deleting
usage, revenue, imported events, or reference mappings.

## Project Structure

```text
app/
  main.py                 Dash app factory and local entry point
  config.py               Environment-based settings
  layout.py               Global shell and sidebar navigation
  routes.py               Page routing
  pages/                  Dash page layouts
  components/             Reusable KPI, chart, table, filter, and form components
  domain/                 Pure business logic and domain models
  data/                   Database setup, ORM schemas, repositories, seed helpers
  integrations/           Placeholder API clients for future systems
  utils/                  Formatting, dates, and validation helpers
tests/                    Unit tests for pricing, costs, and unit economics
data/                     CSV seed data
migrations/               Reserved for Alembic migrations
```

## Add a New Service Line

1. Add the service definition in `SeedRepository.services()` or the future `services` table.
2. Add usage event types to `data/seed_usage.csv`.
3. Add matching variable cost rates to `data/seed_costs.csv`.
4. Add pricing fields or event mapping in `app/domain/revenue_engine.py` if the service has billable units.
5. Add charts or tables in the relevant page module if the service needs custom display.

## Operational Usage

`valteh-revenue-api` is the only component that connects to operational source
systems. It stores raw events, resolves source-scoped client references,
classifies successful events, and writes normalized records to the shared
`usage_events` table. This console reads those rows through its existing SQL
repository; it does not hold source URLs or tokens. The full contract and
architecture live in:

- `docs/shared-operational-event-contract.md`
- `docs/event-consumption-architecture.md`

### Shared database pipeline

Each source system exposes `GET /api/operational-events` (cursor-paginated).
The API pulls those pages and stores raw facts idempotently. Its corresponding
modules are:

- `app/domain/operational_events.py` — Pydantic contract models.
- `app/integrations/operational_events_client.py` — HTTP client (`httpx`).
- `app/integrations/ingestion.py` — idempotent sync, dedup by
  `(source_system, source_event_id)`, cursor tracking.
- `app/integrations/sync_runner.py` — entry point.

Configure source URLs and tokens in the API `.env`, then run from the API
repository:

```bash
python -m app.integrations.sync_runner
```

Imported events land in `imported_operational_events`; successful recognized
events normalize into `usage_events`. Nullable `usage_events.imported_event_id`
provides provenance while existing manual and seed records remain compatible.
The API deployment runs `alembic upgrade head` before either application starts.
Both repositories carry the identical shared-schema migration revision.

### Legacy placeholders

The earlier mock integration placeholders still live in `app/integrations/`
(`fetch_saremi_usage()`, `fetch_llm_token_usage()`, `fetch_graphos_usage()`,
`fetch_blockchain_usage()`, `fetch_platform_clients()`). They are superseded by
the API-owned pipeline and kept only as inert references. They are not used by
the dashboard runtime; operational credentials belong only in the API environment.

### Claude Console usage and cost reporting

The Usage page can load API token usage, Claude Code analytics, and organization cost reports directly from Anthropic's
Admin API. This is a server-side administrative reporting integration, not an operational source-system
connection: the browser receives only report values and never receives the Admin API key.

For local development, set the key only in the ignored `.env` file:

```text
ANTHROPIC_ADMIN_KEY=sk-ant-admin...
```

Restart the application after changing `.env`. In production, configure `ANTHROPIC_ADMIN_KEY` as a
runtime secret on the console service instead of uploading `.env`. Never place the value in
`.env.example`, source code, Docker build arguments, database records, or logs. The repository's
`.dockerignore` excludes local environment files from Docker images.

The **Historical** subtab shows all persisted history, while **Live API** reports are loaded on demand for a
maximum range of 31 days. The latest successful Live report is cached only for the current browser session so it
survives page and subtab changes; it is not written to the historical database. The page can filter and group
usage by API key, workspace, model, environment, and client. API-key-to-client assignments are persisted as client external references
(`anthropic_development`, `anthropic_staging`, `anthropic_production`, or `anthropic_internal`).

Anthropic exposes token usage by API key, but its Cost API does not expose API key as a cost dimension. The
dashboard therefore allocates each daily billed cost line to matching API keys by workspace, model, and
token/tool type, proportional to the measured usage units. Any line that cannot be matched remains visible as
unallocated cost so that the allocation always reconciles to the organization bill without silently inventing
ownership.

Durable Anthropic history is synchronized by the explicit **Update history** action or the `anthropic-history`
CLI; both use the same idempotent service. Dashboard Live reports remain outside the database, and merely opening
or reading the historical dashboard never calls Anthropic or writes synchronization data. See
[Anthropic History Operations](docs/anthropic-history.md) for bootstrap, incremental, repair, scheduling,
reconciliation, and recovery procedures.

## Production Notes

Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL, for example:

```text
postgresql+psycopg2://user:password@host:5432/valteh_economics
```

Keep business calculations in `app/domain/`. Dash callbacks and page modules should call domain functions and repositories rather than embedding pricing, cost, or margin logic directly in the UI.
