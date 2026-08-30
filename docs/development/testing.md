# Testing and validation

Prefer the narrowest suite that proves the change, then broaden when a boundary or shared model changed.

```bash
python -m pytest tests/test_unit_economics.py tests/test_executive_dashboard.py
python -m pytest tests/test_pricing_engine.py tests/test_pricing_simulator.py
python -m pytest tests/test_cost_engine.py tests/test_cost_management.py
python -m pytest tests/test_anthropic_history_sync.py tests/test_anthropic_admin_api.py
python -m pytest tests/test_operational_event_migration.py tests/test_operational_usage_repository.py
python -m pytest
python -m ruff check .
python -m black --check .
```

Add regression tests for domain edge cases, transactional failures, effective-date boundaries, migrations, provider validation, and important UI states. UI tests in this repository commonly inspect Dash component structures and callback registration without a browser.

Do not claim a check passed unless it ran successfully. Networked provider tests should use injected/fake openers; unit tests must not require real secrets.
