# Valteh Revenue Console

Internal dashboard for monitoring Valteh's revenue, costs, usage, pricing, clients, and operating margins across
SAREMI, Graphos, Blockchain/BaaS, and SIGEN.

The application is a management-accounting console. Revenue events are calculated from effective pricing-plan
subscriptions and billable usage; they are not proof that an invoice was issued or a customer payment was received.

## Main capabilities

- **Executive Dashboard:** monthly revenue, fixed and variable costs, operating margin, burn rate, break-even usage,
  service-line economics, and client profitability.
- **Clients:** durable client records, dated pricing subscriptions, external source references, monthly economics,
  usage history, and calculated revenue events.
- **Costs:** monthly and annual reporting plus versioned management of actual and estimated costs.
- **Pricing:** pricing-plan comparison followed by a one-client simulator, revenue/cost split, and sensitivity analysis.
- **Usage:** operational usage plus Anthropic Admin API usage and allocated costs, with persistent history and temporary
  live reports.
- **Scenarios:** read-only six-month Base, Pessimistic, and Optimistic forecasts.

## Technology

- Python 3.11+
- Dash, Dash Bootstrap Components, Plotly, and Pandas
- SQLAlchemy and Alembic
- SQLite locally; PostgreSQL through `DATABASE_URL`
- Pydantic settings and domain models
- Pytest, Ruff, and Black

## Quick start

```powershell
cd valteh-revenue-console
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m app.main
```

On macOS or Linux, activate the environment with `source .venv/bin/activate` and copy the environment file with
`cp .env.example .env`.

Open [http://127.0.0.1:8050](http://127.0.0.1:8050). The server also accepts a host-provided `PORT` environment
variable.

## Configuration and secrets

Local configuration belongs in the ignored `.env` file. Commit only safe placeholders to `.env.example`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | Browser title and application name | `Valteh Economics Dashboard` |
| `ENVIRONMENT` | Runtime environment label | `development` |
| `DEBUG` | Dash debug mode | `true` |
| `DATABASE_URL` | SQLAlchemy connection URL | `sqlite:///valteh_economics.db` |
| `CURRENCY` | Dashboard reporting currency | `MXN` |
| `ANTHROPIC_ADMIN_KEY` | Server-only Anthropic Admin API credential | unset |
| `ANTHROPIC_HISTORY_OVERLAP_DAYS` | Persisted days refreshed by incremental sync | `7` |

Never place `ANTHROPIC_ADMIN_KEY` in source code, browser state, database rows, logs, Docker build arguments, or a
committed environment file. In production, inject it through the hosting platform's secret manager.

## Data lifecycle

Application startup runs Alembic migrations and initializes reference data when the corresponding tables are empty.
The CSV files under `data/` are initial seed data, not the live editing surface:

- `seed_clients.csv`
- `seed_client_subscriptions.csv`
- `seed_costs.csv`
- `seed_usage.csv`
- `seed_pricing_plans.csv`

After initialization, client and cost changes are stored in the configured SQL database. The app does not rewrite the
CSV files. Cost and subscription changes are date-effective so historical months retain the commercial terms that
applied at the time. Normal lifecycle changes should create or close dated records rather than overwrite history.

Pricing plans can be reusable or dedicated to one client. A dedicated ad-hoc plan is excluded from new-client choices
and cannot be assigned to a different client.

Operational usage is stored in `usage_events`. Source-system credentials and ingestion belong to the separate
`valteh-revenue-api`; this console reads normalized events and maps source-scoped external references to durable client
IDs. See [Operational Event Contract](docs/shared-operational-event-contract.md) and
[Event Consumption Architecture](docs/event-consumption-architecture.md).

## Anthropic usage and cost history

The Usage page has two separate data paths:

- **Historical:** reads all persisted Anthropic usage and billed-cost facts. **Update history** performs an explicit,
  idempotent incremental sync through the latest complete UTC day.
- **Live API:** requests up to 31 days directly from the Admin API. The latest successful result is retained for the
  browser session but is never added to historical storage.

Usage can be filtered or grouped by workspace, API key, model, environment, or client. Charts support Usage/Cost and
Daily/Monthly/Yearly views. Anthropic does not return billed cost by API key, so the dashboard allocates cost using
matching workspace, model, and usage dimensions; unmatched amounts remain explicitly unallocated.

API-key ownership assignments are stored with effective dates. Raw provider facts remain separate from derived cost
allocation.

Useful commands after configuring the Admin key:

```bash
# Validate the initial import without writing
anthropic-history sync --mode bootstrap --dry-run

# Initial import
anthropic-history sync --mode bootstrap

# Ordinary incremental update
anthropic-history sync

# Idempotently repair one month
anthropic-history sync --month 2026-07 --mode repair
```

The module form is `python -m app.integrations.anthropic_history_runner ...`. Detailed operating and recovery guidance
is in [Anthropic History Operations](docs/anthropic-history.md).

## Development commands

```bash
python -m pytest
python -m ruff check .
python -m black .
python -m alembic upgrade head
```

For a focused change, prefer the relevant test module instead of running unrelated suites.

## Docker and deployment

```bash
docker compose up --build
```

For Render or a similar host:

```text
Build command: pip install -e .
Start command: gunicorn app.main:server
```

Use a persistent PostgreSQL `DATABASE_URL` in production and manage credentials as runtime secrets. Back up the
database before migrations, historical imports, or administrator-only data corrections.

## Project structure

```text
app/
  main.py          Application factory and server entry point
  config.py        Environment settings
  layout.py        Navigation and shared application shell
  routes.py        Page routing and callback registration
  pages/           Dash page layouts and presentation callbacks
  components/      Reusable tables, charts, forms, and KPI cards
  domain/          Business calculations and provider-independent rules
  data/            ORM schemas, repositories, migrations interface, and seed helpers
  integrations/    Anthropic and other external-system adapters
  assets/          Theme tokens, component styles, and chart theme synchronization
data/              Initial reference CSV files
docs/              User and operator documentation
migrations/        Alembic schema and controlled data migrations
tests/             Domain, repository, migration, and UI-structure tests
```

Keep financial rules in `app/domain/`, persistence in `app/data/`, external APIs in `app/integrations/`, and Dash
callbacks focused on presentation and orchestration. Do not hardcode secrets or client-specific commercial terms in UI
callbacks.

## Additional documentation

- [Dashboard User Guide](docs/dashboard-user-guide.md)
- [Anthropic History Operations](docs/anthropic-history.md)
- [Operational Event Contract](docs/shared-operational-event-contract.md)
- [Event Consumption Architecture](docs/event-consumption-architecture.md)
