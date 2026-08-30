# Coding standards

- Follow `pyproject.toml`: Python 3.11+, 120-character line length, Ruff rules `E`, `F`, `I`, `UP`, and `B`, Black formatting.
- Use `Decimal` for money, prices, rates, and margins. Normalize inputs deliberately; do not introduce binary-float financial formulas.
- Use type hints where they clarify contracts. Prefer explicit control flow and focused functions.
- Validate external and user input at boundaries; raise safe, specific errors.
- Keep Dash callbacks thin. Domain calculations belong in `app/domain/`, transactions in repositories, and provider parsing in integrations.
- Preserve existing historical/versioned behavior and public identifiers.
- Use existing dependencies or the standard library before adding packages.
- Comments explain rationale or constraints, not obvious mechanics.
- Never hardcode credentials or client-specific commercial terms in presentation code.

When changing a rule, update its domain test and any affected presentation-state test. When changing structure, regenerate the repository map.

