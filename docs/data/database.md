# Database lifecycle

The local default is `sqlite:///valteh_economics.db`; production supplies PostgreSQL through `DATABASE_URL`. `app/data/database.py` owns the engine/session factory and invokes Alembic.

Application startup calls `seed_database()`:

1. upgrade to the current Alembic head;
2. seed pricing/client/subscription tables only when empty;
3. seed cost data only when the runtime catalog is empty;
4. idempotently add missing historical usage facts.

CSV files under `data/` are bootstrap inputs, not live storage. Administrative changes go through repositories and SQL transactions. Do not make page callbacks write CSVs or construct ad-hoc sessions.

Repository transactions must validate boundary inputs, preserve history, rollback atomically on failure, and surface useful domain-specific errors. Back up production data before migrations, bulk history imports, or administrator corrections.

