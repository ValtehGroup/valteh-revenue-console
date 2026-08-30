# Agent Guide

This file is the canonical entry point for coding agents. Keep it short; load only the documents relevant to the task.

## Start here

1. Read [`docs/INDEX.md`](docs/INDEX.md) and select the smallest relevant context set.
2. Inspect the implementation and tests named by those documents. Code and tests are the runtime source of truth.
3. Check [`docs/decisions/`](docs/decisions/) only when the task touches a documented architectural boundary.
4. Make the smallest coherent change and run focused validation from [`docs/development/testing.md`](docs/development/testing.md).

## Non-negotiable boundaries

- Put financial and domain rules in `app/domain/`; do not duplicate formulas in Dash callbacks.
- Treat `app/pages/` as presentation and orchestration. A UI state that is unavailable or not applicable must be represented there without weakening domain validation.
- Preserve date-effective commercial, cost, assignment, and FX history. Prefer new/closed records over rewriting history.
- Keep persistence in `app/data/` and provider I/O in `app/integrations/`.
- Validate external data at its boundary and keep provider facts separate from derived allocations.
- Never commit secrets, credentials, raw PII, `.env`, or database files. Do not expose secrets in URLs, logs, browser state, or documentation.
- Alembic migrations are the schema authority. Keep the console and `valteh-revenue-api` on a compatible linear revision chain.

## Known invariant

`app/domain/unit_economics.py::calculate_break_even_usage()` requires `unit_price > unit_variable_cost` and raises otherwise. Callers such as `app/pages/executive_dashboard.py` must use `break_even_usage = None` plus an explanatory note when break-even is not applicable. Do not change the domain guard to solve a display problem.

## Useful commands

```bash
python -m app.main
python -m pytest tests/test_unit_economics.py tests/test_executive_dashboard.py
python -m pytest
python -m ruff check .
python -m black --check .
python -m alembic upgrade head
```

Local setup and platform-specific commands are in [`docs/development/setup.md`](docs/development/setup.md).

## Keep context healthy

- Update the closest modular document when behavior or intent changes.
- Add an ADR only for a durable cross-cutting decision; do not use ADRs as changelogs.
- Keep speculative integrations and unapproved roadmap ideas outside the agent context.
- Keep documents factual and lightweight. Do not place secrets, raw PII, or business data in them.
