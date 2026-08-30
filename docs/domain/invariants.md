# Domain invariants

These rules are protected by domain/repository validation and tests. A caller must adapt its presentation or workflow rather than bypass them.

1. `calculate_break_even_usage()` accepts only `unit_price > unit_variable_cost`; `tests/test_unit_economics.py` covers the rejection. `tests/test_executive_dashboard.py` covers `n/a` UI states.
2. Client and cost lifecycle end dates cannot precede start dates.
3. Actual cost versions for a `cost_key` cannot overlap. Economic changes create versions; metadata corrections preserve the record identity.
4. Subscription changes preserve prior history and reject overlaps. Dedicated plans remain bound to their client.
5. Optimistic locking through `updated_at` prevents silent client/cost overwrites.
6. Operational imports deduplicate by source provenance; SAREMI logical documents additionally deduplicate by canonical billable unit.
7. Demo, non-production, and non-billable events do not enter production revenue/cost KPIs.
8. Historical Anthropic syncs are transactional and idempotent; failed persistence does not advance watermarks.
9. Provider facts remain separate from derived ownership/cost allocation; unmatched values are visible.
10. Dated FX resolution never looks forward and source values are not mutated by display translation.
11. Secrets are server-only, redacted by settings, and absent from URLs, browser state, committed environment files, and logs.
12. Database schema changes use Alembic and preserve compatibility with the shared API revision chain.

If code and this list disagree, inspect the associated tests and recent migrations before changing either.

