# Migrations

Alembic is the schema authority. Resolve the current head from the repository rather than copying a revision into context that can become stale.

## Workflow

```bash
python -m alembic heads
python -m alembic upgrade head
python -m pytest tests/test_cost_migration.py tests/test_operational_event_migration.py
```

For a new migration:

- base it on the current head and keep one linear chain;
- update `app/data/schemas.py` in the same change;
- preserve existing data and date-effective history;
- make controlled data transformations explicit and refuse unsafe/unexpected production states;
- add focused upgrade tests and, when supported, downgrade safety tests;
- verify compatibility expectations with `valteh-revenue-api` for shared tables.

Never replace a migration with `Base.metadata.create_all()` as the deployment strategy.
