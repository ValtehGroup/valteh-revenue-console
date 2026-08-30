# Local setup

The project requires Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m alembic upgrade head
python -m app.main
```

On macOS/Linux use `source .venv/bin/activate` and `cp .env.example .env`. The application listens on `http://127.0.0.1:8050` by default.

Settings are loaded by `app/config.py`. Keep `.env` local and commit only safe placeholders in `.env.example`. Production uses a persistent PostgreSQL `DATABASE_URL` and runtime secret management.

Docker development is available through `docker compose up --build`; the production entry point is `gunicorn app.main:server`.

