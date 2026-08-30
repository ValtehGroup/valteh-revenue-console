# Debugging guide

## Application fails during startup

Startup runs migrations and seed initialization before the Dash server is created. Check `DATABASE_URL`, the Alembic head, migration errors, and seed validation before debugging page routing.

## A historical number changed

Inspect the effective subscription, pricing snapshot, cost version, usage provenance, and recognition/valuation date. Do not patch the page formula. Repository projections and domain engines should reproduce the number for the selected month.

## Break-even shows `n/a`

This is expected when there is no positive per-document price, unit price does not cover variable cost, or usage is pending. The UI owns the explanatory state; the domain guard stays strict.

## Anthropic history differs from live

The paths are intentionally separate. Compare requested dates, completed UTC days, watermarks, persisted range, workspace/model dimensions, and unallocated cost. Never repair history by copying session-live data.

## USD display fails

Check persisted Banxico FIX coverage for each recognition/valuation date. Resolution may use the latest prior valid rate but never a future rate; missing/stale data should remain an explicit error.

## Focused diagnostics

Use the closest repository/domain test first. Provider adapters accept injected openers, and repositories accept session factories, so failures can normally be reproduced without real network calls or production data.

