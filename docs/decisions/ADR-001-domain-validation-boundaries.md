# ADR-001: Domain validation boundaries

- Status: Accepted
- Date: 2026-08-30

## Context

The console presents calculations whose inputs can make a metric unavailable or not applicable. Relaxing a domain precondition to avoid a UI exception would allow invalid values to propagate into other callers and obscure the reason a calculation has no meaning.

The concrete case is `calculate_break_even_usage()` in `app/domain/unit_economics.py`. Break-even usage requires positive unit contribution margin, so `unit_price` must be greater than `unit_variable_cost`.

## Decision

Domain functions keep strict mathematical and business preconditions and raise clear errors for invalid inputs. Presentation/application callers inspect expected availability conditions and represent non-applicable results explicitly, normally with `None` plus a user-facing explanation.

Dash callbacks must not duplicate or weaken the domain formula. Boundary validation belongs at the closest authoritative layer: provider parsing in integrations, transaction/history rules in repositories, financial rules in domain code, and display-state selection in pages.

## Consequences

- Invalid calculations cannot silently become plausible numbers.
- Non-applicable UI states require explicit handling and tests.
- Reusable domain functions remain consistent across pages and future APIs.
- `tests/test_unit_economics.py` protects the guard; `tests/test_executive_dashboard.py` protects `n/a` rendering for known conditions.

