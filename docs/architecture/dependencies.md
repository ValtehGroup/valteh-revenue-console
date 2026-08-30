# Dependencies and infrastructure

The project targets Python 3.11+ and declares dependencies in `pyproject.toml`.

| Dependency | Role |
| --- | --- |
| Dash, Dash Bootstrap Components | Application shell, pages, callbacks, UI components |
| Plotly, Pandas | Charts and tabular transformations |
| SQLAlchemy, Alembic | Persistence and schema migrations |
| Pydantic, pydantic-settings | Domain/boundary validation and environment settings |
| psycopg2-binary | PostgreSQL driver |
| Gunicorn | Production WSGI server |
| Pytest, Ruff, Black | Development validation |

SQLite is the local default; production should provide PostgreSQL through `DATABASE_URL`. External HTTP adapters use the Python standard library and server-only credentials from settings.

Before adding a dependency, confirm the standard library and existing packages are insufficient and that the dependency materially lowers complexity or risk. Do not upgrade unrelated packages in feature work.

