# SAREMI pricing and future usage contract

## Commercial model

`pricing_plans` contains immutable catalog versions. A price change creates a new row/version; it does not edit a
version referenced by a client agreement. `client_subscriptions` is the effective agreement and stores authoritative
snapshots for monthly, annual, included-document, overage, setup, one-time, discount, and channel terms. Revenue uses
those snapshots.

Platform and API are distinct service lines. Enterprise and API Enterprise are informational until complete custom
terms are approved. API 10K is visible but not assignable until infrastructure capacity is validated. When real data
exists, review API 10K if measured COGS per document approaches MXN 1.10; this is an internal review guardrail, not a
public technical limit.

New agreements are temporarily limited to a billing-cycle anchor on day 1. Capacity resets monthly, does not roll
over, and overage starts with the first billable document above contracted capacity. A non-calendar-cycle proration
and revenue-recognition policy must be approved before relaxing this validation.

## Usage availability

Agreement usage state is explicit:

- `pending`: the SAREMI source is not connected; usage is unknown, not zero, and cannot generate overage.
- `available`: production billable events are connected; an empty cycle is a measured zero.
- `demo`: synthetic data for UI/testing, excluded from production revenue, cost, utilization, and KPIs.

The Notaría 38 pilot remains a MXN 5,000 one-time agreement with 500 included documents, no recurring fee, included
setup, no new overage, and pending usage. The approximate 450 documents are deliberately not stored as events.

## Canonical future billable event

The normalized event type is `saremi.processed_document`. It represents one logical document that reached a usable
terminal result. It is not a Claude call, individual validation, page, token quantity, internal retry, or failed
upload. `quantity` is normally 1 and `billable_unit_id` identifies the logical unit; duplicate events with the same
billable unit do not multiply revenue. Sandbox/staging and `is_billable=false` events never bill. A client resubmission
may bill only when SAREMI supplies a distinct billable-unit identity under the approved commercial rule.

Future SAREMI telemetry should preserve `document_processing_id`, `billable_unit_id`, client/institution reference,
environment, terminal status, billable flag and reason, retry/correlation relationship, document type or hash,
processed timestamp, API key ID, model, and token dimensions.

## Claude cost attribution

Anthropic Admin API facts remain real and unchanged. API-key ownership is resolved through date-effective client
assignments; unmatched cost remains unassigned and reconcilable. The Admin API is aggregate and cannot by itself
produce exact document cost. Exact document attribution requires SAREMI correlation telemetry; until then the console
must show aggregate/assigned client or period cost and must not divide cost by an estimated document count.

This change does not implement a SAREMI HTTP client, synchronization, queues, invoice ledger, or external alerts.
