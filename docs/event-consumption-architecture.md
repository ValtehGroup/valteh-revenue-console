# Event Consumption Architecture

## 1. Purpose

`valteh-revenue-api` consumes operational events from systems such as `baas-qro` and `rpp-fraud-detection-system`, classifies them, and writes normalized usage to the PostgreSQL database shared with `valteh-revenue-console`.

Source systems emit facts only. They record what happened: a document was validated, a fraud alert was created, a property was minted, a certificate was issued, or a chaincode was invoked. They must not calculate prices, costs, revenue, margins, invoices, billing, or profitability.

The revenue API consumes those facts and classifies them into:

- Usage metrics.
- Billable events.
- Cost-relevant events.
- Client-visible events.
- Internal-only events.
- Monthly revenue, cost, margin, billing, and profitability inputs.

The purpose is to create a clean boundary: operational systems stay focused on operational truth, the API owns ingestion and normalization, and the console keeps its existing SQL-backed economic views and calculations during this transition.

### Transitional runtime flow

```text
Operational source systems
    -> valteh-revenue-api (raw import, checkpoint, classification)
    -> shared PostgreSQL (raw events and normalized usage_events)
    -> valteh-revenue-console (existing SQL repositories and dashboards)
```

Only the API stores source URLs and tokens or calls source export endpoints.
The console carries matching ORM and Alembic metadata solely for shared-schema
compatibility.

## 2. Responsibility Boundary

### Source Systems

Systems such as `baas-qro` and `rpp-fraud-detection-system` are responsible for operational events only.

Examples:

- `blockchain.document_anchored`
- `blockchain.property_minted`
- `blockchain.property_transferred`
- `registry.inscription_completed`
- `registry.certificate_issued`
- `identity.validation_completed`
- `document.analysis_completed`
- `fraud.alert_created`
- `fraud.manual_review_required`

Source systems should send:

- Event type.
- Event timestamp.
- Source system.
- External event ID.
- Correlation ID.
- Client, entity, property, document, or profile identifiers where available.
- Operational metadata.
- Status and error details where applicable.

Source systems should not send:

- Price.
- Cost.
- Revenue.
- Margin.
- Invoice ID.
- Billing period.
- Pricing plan.
- Included quantity.
- Discount.
- Tax.
- Profitability classification.

### valteh-revenue-api and valteh-revenue-console

The API is responsible for importing, resolving client references, classifying,
normalizing, and preserving provenance. The console is responsible for applying
the existing economic models and presenting the results. Together they provide:

- Mapping imported operational events to clients.
- Classifying events.
- Converting operational events into normalized local `UsageEvent` records.
- Applying pricing plans and included quantities.
- Applying variable and fixed cost rules.
- Calculating revenue.
- Calculating margins and client profitability.
- Producing billing inputs and invoice-ready summaries.
- Producing internal and client-facing economic analytics.

Client identity resolution uses the pair `(source_system, client_reference)` and the
`client_external_references` table. API credentials authenticate a source connection;
they never identify a client. Raw imported events remain stored when no mapping exists,
so a reference added later can resolve and classify those events without re-ingestion.

All economic interpretation must happen here.

## 3. Proposed Local Data Model

The current app already has SQLAlchemy/Pydantic models for:

- `clients`
- `services`
- `pricing_plans`
- `client_subscriptions`
- `usage_events`
- `cost_items`
- `revenue_events`
- `scenario_assumptions`

To support imported operational events cleanly, add local ingestion models without changing source-system contracts.

### `imported_operational_events`

Stores raw source facts exactly as received, after minimal validation and redaction.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer/uuid | Local primary key. |
| `source_system` | string | Example: `baas-qro`, `rpp-fraud-detection-system`. |
| `source_event_id` | string | Event ID from the source system. |
| `event_type` | string | Original source event type. |
| `event_category` | string | Original category if provided. |
| `occurred_at` | datetime | Source event timestamp. |
| `received_at` | datetime | Import timestamp. |
| `correlation_id` | string | Source workflow correlation ID. |
| `external_reference_id` | string | Optional source reference ID. |
| `source_client_ref` | string | Client/entity/notary identifier from source metadata. |
| `document_id` | string | Optional document ID. |
| `document_hash` | string | Optional document hash. |
| `property_id` | string | Optional property ID. |
| `profile_id` | string | Optional client profile ID. |
| `status` | string | Source status such as `succeeded`, `failed`, `requires_review`. |
| `raw_payload_json` | text/json | Redacted source event payload. |
| `import_status` | string | `imported`, `classified`, `ignored`, `error`. |
| `classification_error` | text | Error detail if classification failed. |

Recommended uniqueness:

- `(source_system, source_event_id)`

### `event_classifications`

Stores the local interpretation of a source event.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer/uuid | Primary key. |
| `imported_event_id` | fk | Links to `imported_operational_events`. |
| `client_id` | integer | Local client. |
| `service_code` | string | Current service codes include `saremi`, `graphos`, `blockchain`, `sigen`. |
| `usage_event_type` | string | Local usage type such as `saremi.document_validation`. |
| `classification` | string | `usage_metric`, `billable`, `cost_relevant`, `client_visible`, `internal_only`. |
| `quantity` | decimal | Local quantity after classification. |
| `unit` | string | Local unit such as `document`, `validation`, `query`, `event`, `folio`. |
| `is_billable` | boolean | Whether pricing rules should consider it for usage revenue. |
| `is_cost_relevant` | boolean | Whether cost rules should consider it. |
| `is_client_visible` | boolean | Whether client reports may show it. |
| `is_internal_only` | boolean | Whether it should stay internal. |
| `classification_reason` | text | Human-readable rule explanation. |
| `metadata_json` | text/json | Safe normalized metadata. |

### `usage_events`

The existing `usage_events` model should remain the normalized economic input table.

Imported operational events should become `usage_events` only after classification. This keeps source payloads separate from economic usage facts.

Existing fields:

- `client_id`
- `service_code`
- `event_type`
- `quantity`
- `unit`
- `event_timestamp`
- `source_system`
- `external_reference_id`
- `metadata_json`

### `event_import_cursors`

Tracks idempotent synchronization.

| Field | Type | Notes |
| --- | --- | --- |
| `source_system` | string | Example: `baas-qro`. |
| `cursor` | string | Source pagination cursor. |
| `last_occurred_at` | datetime | Last synced event timestamp. |
| `last_successful_sync_at` | datetime | Last successful import run. |
| `status` | string | `ok`, `error`, `paused`. |
| `error_message` | text | Last sync error. |

## 4. Event Classification Rules

Classification converts raw operational events into local economic and reporting meaning.

Classification must be deterministic, versioned, and owned by this app.

### Classification Types

`usage_metric`:

- Counts toward product usage metrics.
- May or may not be billable.
- Example: `fraud.alert_created`.

`billable`:

- Eligible for usage pricing after included quantities and subscription terms.
- Example: successful `identity.validation_completed` mapped to `saremi.ine_validation`.

`cost_relevant`:

- Drives variable cost calculations.
- Example: `document.analysis_completed` mapped to AI document-processing cost.

`client_visible`:

- Safe to show in client-facing reports.
- Example: document validations completed, certificates issued, property folios minted.

`internal_only`:

- Operational event useful internally but not shown to clients and not billed directly.
- Example: failed retries, graph debug reads, internal health checks, ingestion errors.

### Source Event Mapping Examples

From `rpp-fraud-detection-system`:

| Source event | Local service | Local usage event | Default classification |
| --- | --- | --- | --- |
| `document.analysis_completed` | `saremi` | `saremi.document_validation` | billable, cost_relevant, client_visible |
| `identity.validation_completed` | `saremi` | `saremi.ine_validation` | billable, cost_relevant, client_visible |
| `fraud.alert_created` | `saremi` | `saremi.fraud_alert` | usage_metric, client_visible or internal_only by severity/config |
| `fraud.manual_review_required` | `saremi` | `saremi.manual_review_required` | usage_metric, cost_relevant, client_visible |
| `fraud.manual_review_completed` | `saremi` | `saremi.manual_review_completed` | usage_metric, cost_relevant, client_visible |
| `graph.fraud_network_requested` | `graphos` | `graphos.query` | billable or internal_only by caller/reporting policy |
| `graph.client_profile_requested` | `graphos` | `graphos.query` | usage_metric or billable by plan |

From `baas-qro`:

| Source event | Local service | Local usage event | Default classification |
| --- | --- | --- | --- |
| `blockchain.document_anchored` | `blockchain` | `blockchain.asiento_registration` | billable, cost_relevant, client_visible |
| `registry.inscription_completed` | `blockchain` | `blockchain.asiento_registration` | billable, client_visible |
| `registry.certificate_issued` | `blockchain` | `blockchain.certificate_issued` | billable, cost_relevant, client_visible |
| `blockchain.property_minted` | `blockchain` | `blockchain.folio_mint` | billable, cost_relevant, client_visible |
| `blockchain.property_transferred` | `blockchain` | `blockchain.property_transfer` | usage_metric or billable by plan |
| `blockchain.chaincode_invoked` | `blockchain` | `blockchain.chaincode_invocation` | internal_only or billable by contract |
| `blockchain.chaincode_queried` | `blockchain` | `blockchain.chaincode_query` | internal_only or billable by contract |

### Deduplication Rules

Some source systems may emit both legal and technical events for one workflow. For example:

- `blockchain.document_anchored`
- `blockchain.property_minted`
- `registry.inscription_completed`

The revenue console must decide whether these are separate billable units or one bundled activity.

Recommended approach:

- Use `correlation_id`, `external_reference_id`, `document_hash`, `property_id`, and `occurred_at` to detect related events.
- Keep all raw events in `imported_operational_events`.
- Generate one or more `usage_events` according to local classification rules.
- Mark duplicates or supporting events as `usage_metric` or `internal_only` when they should not generate additional billable usage.

### Status Rules

Default treatment:

- `succeeded` or `completed`: eligible for usage, pricing, cost, and reports.
- `failed`: internal-only unless the failure consumes paid resources.
- `requires_review`: usage_metric and possibly cost_relevant.
- `rejected`: client-visible only if it represents a completed validation result.

## 5. Pricing Rules

Pricing must be calculated only inside `valteh-revenue-console`.

The source event contains operational facts. The local pricing engine determines whether and how to charge.

Current pricing engine:

- Uses `PricingPlan`.
- Uses `ClientSubscription`.
- Uses local usage event types.
- Applies included quantities.
- Calculates setup, annual, monthly fixed, and usage revenue.

Current event price mapping lives in `app/domain/revenue_engine.py`:

```text
saremi.document_validation -> price_per_document
saremi.ine_validation -> price_per_validation
graphos.query -> price_per_graph_query
graphos.case_analysis -> price_per_graph_query
blockchain.asiento_registration -> price_per_blockchain_transaction
blockchain.certificate_issued -> price_per_blockchain_transaction
blockchain.folio_mint -> price_per_property_mint
```

Recommended pricing rule flow:

1. Determine `client_id` from source metadata and local client mapping.
2. Determine active subscription for the event month.
3. Map source event to local `usage_event_type`.
4. Determine whether event is billable.
5. Apply included quantities for the active plan.
6. Apply local unit price from the plan.
7. Produce revenue events or invoice-ready line items.

Rules:

- Never trust source-system price fields.
- Ignore any source-system cost, price, revenue, margin, billing, or invoice fields if they appear accidentally.
- Price only normalized local usage events.
- Keep bundled pricing rules local. For example, a property registration may include document anchoring, property minting, and certificate issuance under one commercial unit.
- Support plan-specific overrides inside this app, not in source systems.

## 6. Cost Rules

Costs must be calculated only inside `valteh-revenue-console`.

The current cost engine:

- Uses `CostItem`.
- Treats `fixed` and `one_time` costs as period costs.
- Treats `variable` costs as unit rates keyed by usage event type.

Current variable cost examples:

```text
saremi.document_validation
saremi.ine_validation
graphos.query
graphos.case_analysis
blockchain.asiento_registration
blockchain.folio_mint
```

Recommended cost rule flow:

1. Classify imported event as cost-relevant or not.
2. Convert it to a local `usage_event_type`.
3. Match active `CostItem` variable rates by local event type.
4. Multiply quantity by local unit cost.
5. Add fixed and one-time period costs for monthly summaries.

Rules:

- Failed source events are cost-relevant only if they consumed meaningful variable resources.
- Manual review events may be cost-relevant if local cost rates exist for review labor.
- Internal graph queries may be cost-relevant even if not billable.
- Fixed infrastructure costs are configured locally in `cost_items`, not sent by source systems.
- Benchmark costs should remain inactive until intentionally enabled.

## 7. Client Reporting Rules

Client reports should show operationally meaningful activity without exposing internal implementation details or sensitive raw payloads.

Client-visible examples:

- Documents validated.
- Identity validations completed.
- Fraud alerts by severity.
- Manual reviews required and completed.
- Certificates issued.
- Registry inscriptions completed.
- Property folios minted.
- Blockchain anchors completed.

Internal-only examples:

- Provider retries.
- Debug graph queries.
- Failed background jobs.
- Internal chaincode queries used for diagnostics.
- Raw Livo payload fields.
- Internal cost classifications.
- Pricing-rule decisions unless the report is explicitly invoice-facing.

Rules:

- Use local `is_client_visible` classification.
- Redact personally identifiable information unless the report is authorized to show it.
- Prefer counts, statuses, document IDs, hashes, and workflow references over raw extracted identity payloads.
- Show billable usage separately from non-billable operational activity.
- Show invoice-ready usage only after local pricing rules have run.
- Preserve operational detail for audit, but do not leak internal-only events into client dashboards.

## 8. Monthly Aggregation Logic

Monthly aggregation is the core economic workflow.

Recommended monthly pipeline:

1. Import operational events from source systems by cursor or timestamp.
2. Deduplicate using `(source_system, source_event_id)`.
3. Classify events into local categories.
4. Map events to local clients.
5. Create normalized local `usage_events`.
6. Determine active client subscription for each month.
7. Aggregate usage by client, service, event type, and month.
8. Apply included quantities.
9. Calculate usage revenue.
10. Add monthly fixed, setup, and annual fees.
11. Calculate variable costs from usage.
12. Add fixed and one-time costs for the month.
13. Calculate gross margin and operating margin.
14. Persist or expose revenue events, invoice-ready summaries, and dashboard metrics.

Aggregation dimensions:

- Month.
- Client.
- Service line.
- Source system.
- Event type.
- Billable vs non-billable.
- Client-visible vs internal-only.
- Cost-relevant vs non-cost-relevant.

Current repository methods already support:

- `available_months()`
- `usage_for_month()`
- `usage_for_client_month()`
- `client_revenue_split()`
- `monthly_revenue_split()`
- `monthly_summary()`
- `revenue_by_service()`
- `cost_by_service()`
- `client_profitability()`

The imported-event pipeline should feed these methods through normalized `UsageEvent` records.

## 9. Dashboard Metrics

Recommended dashboard metrics from imported events and local economic interpretation:

### Executive Summary

- Monthly recurring revenue.
- Usage revenue.
- Total revenue.
- Variable cost.
- Fixed cost.
- Gross margin.
- Operating margin.
- Burn rate.
- Revenue by service line.
- Cost by service line.
- Active clients.
- Pipeline clients.

### Usage Dashboard

- Usage by service.
- Usage by client.
- Billable usage.
- Non-billable usage.
- Cost-relevant usage.
- Client-visible activity.
- Internal-only operational activity.
- Source-system import volume.
- Event classification errors.

### Client Detail

- Monthly usage by event type.
- Subscription plan and included quantities.
- Billable quantity after included usage.
- Revenue split: fixed vs usage.
- Variable cost.
- Gross margin.
- Client profitability.
- Client-visible operational summary.

### Pricing Dashboard

- Plan comparison.
- Included quantity utilization.
- Effective unit revenue after included usage.
- Usage overage by event type.
- Minimum unit price using local cost assumptions.
- Break-even usage and client counts.

### Costs Dashboard

- Variable cost by event type.
- Fixed cost by category.
- One-time costs by month.
- Cost per service line.
- Cost per client after allocation if allocation rules are added.
- Cost-relevant source events that are currently non-billable.

### Event Operations Dashboard

- Imported event count by source.
- Classification success rate.
- Classification errors.
- Duplicate events skipped.
- Last successful sync per source.
- Events waiting for client mapping.
- Events ignored by rule.

## 10. Implementation Phases

### Phase 1: Ingestion Foundation

- Add local models for `imported_operational_events`, `event_classifications`, and `event_import_cursors`.
- Add source-system client configuration in `.env`.
- Build API clients for `baas-qro` and `rpp-fraud-detection-system` operational-event endpoints.
- Store raw imported events idempotently.
- Add tests for deduplication and cursor handling.

### Phase 2: Classification Engine

- Add a deterministic classification module in `app/domain/`.
- Map source event types to local service codes and usage event types.
- Add billable, cost-relevant, client-visible, and internal-only flags.
- Add client mapping rules.
- Add tests for classification cases and duplicate workflow handling.

### Phase 3: Usage Normalization

- Convert classified imported events into local `UsageEvent` records.
- Preserve source references in `metadata_json` and `external_reference_id`.
- Keep raw imported events separate from normalized usage.
- Add reconciliation views for imported vs classified vs normalized events.

### Phase 4: Economic Calculation Integration

- Feed normalized usage into the existing `revenue_engine`.
- Feed normalized usage into the existing `cost_engine`.
- Extend pricing mappings only inside `app/domain/revenue_engine.py`.
- Extend cost mappings only through local `CostItem` records.
- Add tests for included quantities, usage revenue, variable costs, and margin calculations.

### Phase 5: Client Reporting

- Add client-visible reporting queries.
- Add redaction rules for source metadata.
- Separate billable usage from non-billable operational activity.
- Add client-facing summaries for document validations, identity validations, fraud alerts, certificates, and blockchain activity.

### Phase 6: Dashboards And Monitoring

- Add event ingestion and classification health metrics.
- Add dashboard views for imported event volume, classification errors, and source sync status.
- Add economic dashboards that compare usage, revenue, costs, and margins by client and service line.

### Phase 7: Billing And Invoice Preparation

- Generate invoice-ready line items from local revenue calculations.
- Keep invoice generation and billing policy local to this system.
- Preserve links from invoice-ready lines back to normalized usage events and source operational events for audit.

## Final Boundary Rule

Operational systems emit facts.

`valteh-revenue-console` imports those facts, classifies them, maps them to usage, applies pricing and cost rules, and calculates revenue, margins, billing, invoices, and profitability.

No source system should be required to send prices, costs, revenue, margins, or billing fields.

