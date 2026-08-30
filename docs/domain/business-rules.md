# Business rules

## Commercial history

- Pricing catalog rows are versioned; client subscriptions snapshot contracted terms.
- Normal plan/cost changes close the prior effective record and create a new one. Historical periods keep their original terms.
- Dedicated plans cannot be assigned to another client. Informational/non-assignable plans require the constraints encoded by repositories and migrations.
- Current new SAREMI agreements use a day-1 billing-cycle anchor until a proration policy is approved.

## Revenue and usage

- Subscription, setup, one-time, and usage revenue are calculated in `app/domain/revenue_engine.py`.
- Production, billable, canonical usage drives economics. Demo/non-production/non-billable events do not.
- SAREMI `saremi.processed_document` represents a logical terminal document. `billable_unit_id` prevents retries from multiplying revenue.
- Missing/pending usage is unavailable, not zero; it cannot create overage.

## Costs and currency

- Variable cost uses the rate effective on each event date; multiple cost components may apply to one event type.
- Fixed costs follow their configured frequency and effective dates. Overlapping active versions for the same cost key are invalid.
- Original entered currency/amount is preserved while normalized MXN economics and dated display translations are calculated separately.
- Banxico series `SF43718` is the stored USD/MXN FIX source. Missing or stale required FX history fails explicitly.

## Margins and break-even

- Gross margin = revenue - variable cost.
- Operating margin = revenue - variable cost - allocated fixed cost.
- Break-even usage exists only when unit contribution margin is positive. The domain raises otherwise; UI callers render an unavailable state.

## Anthropic

- Historical provider facts and live reports are separate data paths.
- Sync is explicit, idempotent, and limited to complete UTC days.
- Billed cost is not inherently keyed by API key. Allocation uses matching dimensions; unmatched amounts remain unallocated and reconcilable.
- Exact document-level Claude cost requires SAREMI correlation telemetry; do not infer it from estimated document counts.

For detailed SAREMI rules see [SAREMI pricing and usage](../saremi-pricing-and-usage.md).

