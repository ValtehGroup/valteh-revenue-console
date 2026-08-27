# Shared Operational Event Contract

## Purpose

This document defines the common operational event contract for all Valteh source systems:

- `baas-qro`
- `rpp-fraud-detection-system`
- Future `sigen-plus-front` integrations

Source systems emit operational facts only. They describe what happened in a registry, blockchain, identity, document, fraud, review, or platform workflow.

`valteh-revenue-api` is the sole ingestion and normalization owner. `valteh-revenue-console` remains responsible for presenting pricing, costs, revenue, margins, plans, and client profitability from the shared database.

Source events must not include:

- Price.
- Cost.
- Revenue.
- Margin.
- Invoice.
- Discount.
- Tax.
- Pricing plan.
- Billing period.
- Profitability classification.

## 1. Required Common Fields

Every exported operational event must include these fields.

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Stable source-system event ID. Unique within `source_system`. |
| `source_system` | string | Emitting system, for example `baas-qro`, `rpp-fraud-detection-system`, or `sigen-plus-front`. |
| `event_type` | string | Dot-delimited operational event name, for example `document.analysis_completed`. |
| `event_category` | string | Broad category such as `identity`, `document`, `fraud`, `registry`, `blockchain`, `review`, `graph`, `platform`, or `system`. |
| `occurred_at` | string | ISO-8601 timestamp for when the event happened. |
| `recorded_at` | string | ISO-8601 timestamp for when the source system persisted the event. |
| `status` | string | Normalized event status. See status convention below. |
| `correlation_id` | string | Workflow-level ID shared by all events in the same business process. |
| `schema_version` | string | Contract version, for example `1.0`. |

## 2. Optional Common Fields

Optional fields should be included when known and safe to expose.

| Field | Type | Description |
| --- | --- | --- |
| `causation_id` | string | Event ID that directly caused this event. |
| `idempotency_key` | string | Stable key for safe retries and deduplication. |
| `actor_user_id` | string | Authenticated user ID, if available. |
| `actor_email` | string | Authenticated user email, if safe to expose. |
| `actor_type` | string | `user`, `api_key`, `system`, `job`, or `integration`. |
| `client_reference` | string | Source-side client, entity, notary office, organization, or tenant reference. |
| `entity_id` | string | Source-side organization/entity ID. |
| `notary_office_id` | string | Source-side notary office ID. |
| `property_id` | string | Property ID. |
| `folio_real` | string | Registry folio identifier. |
| `registry_matter_id` | string | Registry case, tramite, expediente, or presentation ID. |
| `document_id` | string | Source-side document ID. |
| `document_type` | string | Source-side document type. |
| `document_hash` | string | File or document hash. |
| `certificate_id` | string | Certificate identifier. |
| `profile_id` | string | Client profile or identity expediente ID. |
| `person_id` | string | Person ID. |
| `fraud_alert_id` | string | Fraud alert ID. |
| `fraud_alert_type` | string | Fraud alert type. |
| `severity` | string | `info`, `warning`, `error`, or `critical`. |
| `risk_score` | number | Operational risk score. This is not an economic score. |
| `validation_provider` | string | Example: `livo`, `neo4j`, `blockchain`, `internal_hash`. |
| `validation_status` | string | Provider-specific validation result normalized where possible. |
| `validation_confidence` | number | Provider confidence score. |
| `blockchain_id` | string | Blockchain/network ID. |
| `chaincode_name` | string | Chaincode name. |
| `chaincode_function` | string | Chaincode function. |
| `channel_name` | string | Fabric channel name. |
| `transaction_id` | string | Blockchain transaction ID. |
| `block_number` | number | Blockchain block number. |
| `external_reference_id` | string | External source reference ID. |
| `quantity` | number | Factual operational count only. Not a price or amount. |
| `unit` | string | Factual unit such as `document`, `validation`, `alert`, `folio`, `certificate`, or `transaction`. |
| `metadata` | object | Redacted operational metadata. |
| `error_code` | string | Stable machine-readable error code. |
| `error_message` | string | Sanitized error message. |

## 3. Naming Convention

Event names must be:

- Lowercase.
- Dot-delimited.
- Past-tense or milestone-oriented.
- Stable over time.
- Operational, not economic.

Format:

```text
<domain>.<action_or_milestone>
```

Recommended domains:

- `identity`
- `document`
- `fraud`
- `registry`
- `blockchain`
- `review`
- `graph`
- `platform`
- `system`

Examples:

- `identity.validation_completed`
- `document.analysis_completed`
- `fraud.alert_created`
- `registry.inscription_completed`
- `blockchain.property_minted`
- `registry.certificate_issued`

Do not use economic event names such as:

- `billing.usage_charged`
- `revenue.created`
- `invoice.line_created`
- `margin.calculated`
- `plan.applied`

## 4. Status Convention

Use these normalized statuses.

| Status | Meaning |
| --- | --- |
| `started` | Workflow step began. |
| `succeeded` | Workflow step completed successfully. |
| `completed` | Human/process milestone completed. Prefer `succeeded` for technical steps. |
| `failed` | Workflow step failed. |
| `rejected` | Input or operation was rejected by validation/business rules. |
| `requires_review` | Manual review is needed. |
| `cancelled` | Workflow step was cancelled. |
| `inconclusive` | Provider or workflow could not determine a clear result. |

Source systems may preserve provider-specific statuses in `validation_status` or `metadata.providerStatus`, but `status` must use the shared convention.

## 5. Correlation ID And Causation ID Rules

`correlation_id` is required.

Rules:

- All events in the same workflow must share one `correlation_id`.
- Accept inbound `X-Correlation-Id` from trusted callers when available.
- Otherwise generate a UUID at the request or workflow boundary.
- Pass the correlation ID through controllers, services, background jobs, and integrations.
- Return `X-Correlation-Id` in API responses when applicable.
- Do not encode pricing, billing, client profitability, or sensitive PII in correlation IDs.

`causation_id` is optional but recommended.

Rules:

- Use `causation_id` to point to the event that directly caused the current event.
- It should contain a source event ID.
- If the cause came from another system, use that system's event ID and keep `source_system` in metadata.

Example workflow:

```text
document.analysis_completed
  causes fraud.alert_created
    causes fraud.manual_review_required
```

All three events share one `correlation_id`. Each later event may point to the prior event through `causation_id`.

## 6. Metadata Rules

`metadata` is for operational context only.

Allowed metadata:

- Provider names and statuses.
- Validation checks.
- Redacted document details.
- Registry office or workflow details.
- Chaincode and blockchain details.
- Alert reasons.
- Manual review reason.
- Safe external references.
- Counts and factual operational dimensions.

Forbidden metadata:

- Price.
- Cost.
- Revenue.
- Margin.
- Invoice data.
- Discount.
- Tax.
- Pricing plan.
- Billing period.
- Profitability labels.

Metadata must be:

- JSON serializable.
- Redacted before export.
- Stable enough for analytics.
- Small enough for operational exports.

Prefer top-level common fields over metadata for shared identifiers such as `document_id`, `property_id`, `transaction_id`, `fraud_alert_id`, and `certificate_id`.

For systems controlled by Valteh, use the revenue console's public `client_code`
(for example `client_0001`) as `client_reference` when practical. Consumers must
still resolve the pair `(source_system, client_reference)` through the external
reference mapping because third-party products may use their own tenant IDs.

## 7. PII And Redaction Rules

Source systems must minimize PII in exported events.

Allowed by default:

- Internal IDs.
- Document hashes.
- Document types.
- Property IDs.
- Registry matter IDs.
- Folio identifiers.
- Notary office IDs.
- Validation status.
- Risk score.
- Alert type and severity.

Avoid by default:

- Full names.
- Raw addresses.
- Phone numbers.
- Email addresses unless needed for actor audit.
- CURP, RFC, INE clave, passport numbers, bank account numbers.
- Raw OCR output.
- Raw Livo or provider payloads.
- Full document text.

When PII is operationally necessary:

- Put only the minimum required value.
- Prefer hashed or tokenized identifiers.
- Redact in export APIs unless caller has explicit permission.
- Do not place raw PII inside `metadata` unless the endpoint is explicitly scoped for secure internal use.

Recommended redaction pattern:

```json
{
  "documentType": "INE",
  "extractedFields": ["curp", "nombre_completo", "direccion"],
  "piiRedacted": true
}
```

## 8. Idempotency Rules

Events must be safe to export, import, and replay.

Rules:

- `id` must be stable and unique within `source_system`.
- `idempotency_key` should be provided when an operation can be retried.
- Export APIs must return the same event with the same ID on repeated reads.
- Consumers should deduplicate by `(source_system, id)`.
- If a source system cannot guarantee stable IDs, it must provide `idempotency_key`.
- Do not mutate historical events to change meaning. Emit a new corrective event instead.

Recommended idempotency key inputs:

- Source system.
- Event type.
- Primary resource ID.
- Workflow/correlation ID.
- Operation attempt or transaction ID.

Example:

```text
baas-qro:blockchain.property_minted:PROP-123:tx-abc123
```

## 9. Export API Response Shape

Source systems should expose operational events through cursor-paginated APIs.

Recommended endpoint:

```text
GET /api/operational-events
```

Recommended filters:

- `from`
- `to`
- `cursor`
- `limit`
- `eventType`
- `eventCategory`
- `status`
- `correlationId`
- `clientReference`
- `entityId`
- `propertyId`
- `documentId`
- `documentHash`
- `certificateId`
- `transactionId`

Response shape:

```json
{
  "data": [
    {
      "id": "evt_01J00000000000000000000001",
      "source_system": "rpp-fraud-detection-system",
      "schema_version": "1.0",
      "event_type": "document.analysis_completed",
      "event_category": "document",
      "occurred_at": "2026-06-06T12:00:00.000Z",
      "recorded_at": "2026-06-06T12:00:01.000Z",
      "status": "succeeded",
      "correlation_id": "3cde0338-6b73-4cb6-8525-33d523fa7cb2",
      "document_id": "doc_456",
      "document_type": "TITLE_DEED",
      "document_hash": "sha256...",
      "property_id": "prop_123",
      "quantity": 1,
      "unit": "document",
      "metadata": {
        "provider": "livo",
        "piiRedacted": true
      }
    }
  ],
  "pagination": {
    "next_cursor": "eyJvY2N1cnJlZEF0IjoiMjAyNi0wNi0wNlQxMjowMDowMC4wMDBaIn0=",
    "has_more": true
  }
}
```

Errors should use a conventional shape:

```json
{
  "error": {
    "code": "invalid_cursor",
    "message": "The supplied cursor is invalid or expired",
    "correlation_id": "3cde0338-6b73-4cb6-8525-33d523fa7cb2"
  }
}
```

## 10. Examples

### `identity.validation_completed`

```json
{
  "id": "evt_rpp_000001",
  "source_system": "rpp-fraud-detection-system",
  "schema_version": "1.0",
  "event_type": "identity.validation_completed",
  "event_category": "identity",
  "occurred_at": "2026-06-06T10:15:00.000Z",
  "recorded_at": "2026-06-06T10:15:01.000Z",
  "status": "succeeded",
  "correlation_id": "7c06d8c4-2c6b-4420-bb63-b9fb5f8ab7e3",
  "actor_type": "user",
  "actor_email": "operator@example.com",
  "client_reference": "notary-38-qro",
  "profile_id": "profile_123",
  "document_id": "client_doc_456",
  "document_type": "INE",
  "document_hash": "sha256...",
  "validation_provider": "livo",
  "validation_status": "valid",
  "validation_confidence": 0.94,
  "quantity": 1,
  "unit": "validation",
  "metadata": {
    "extractedFields": ["curp", "nombre_completo", "direccion"],
    "piiRedacted": true
  }
}
```

### `document.analysis_completed`

```json
{
  "id": "evt_rpp_000002",
  "source_system": "rpp-fraud-detection-system",
  "schema_version": "1.0",
  "event_type": "document.analysis_completed",
  "event_category": "document",
  "occurred_at": "2026-06-06T10:20:00.000Z",
  "recorded_at": "2026-06-06T10:20:02.000Z",
  "status": "succeeded",
  "correlation_id": "7c06d8c4-2c6b-4420-bb63-b9fb5f8ab7e3",
  "client_reference": "notary-38-qro",
  "property_id": "prop_123",
  "document_id": "doc_789",
  "document_type": "TITLE_DEED",
  "document_hash": "sha256...",
  "validation_provider": "livo",
  "validation_status": "valid",
  "validation_confidence": 0.91,
  "risk_score": 15,
  "quantity": 1,
  "unit": "document",
  "metadata": {
    "fraudAlertCount": 0,
    "baasFileId": "file_abc",
    "piiRedacted": true
  }
}
```

### `fraud.alert_created`

```json
{
  "id": "evt_rpp_000003",
  "source_system": "rpp-fraud-detection-system",
  "schema_version": "1.0",
  "event_type": "fraud.alert_created",
  "event_category": "fraud",
  "occurred_at": "2026-06-06T10:21:00.000Z",
  "recorded_at": "2026-06-06T10:21:01.000Z",
  "status": "succeeded",
  "severity": "warning",
  "correlation_id": "7c06d8c4-2c6b-4420-bb63-b9fb5f8ab7e3",
  "causation_id": "evt_rpp_000002",
  "client_reference": "notary-38-qro",
  "property_id": "prop_123",
  "document_id": "doc_789",
  "document_hash": "sha256...",
  "fraud_alert_id": "alert_123",
  "fraud_alert_type": "DUPLICATE_DOCUMENT",
  "risk_score": 75,
  "quantity": 1,
  "unit": "alert",
  "metadata": {
    "fraudSeverity": "HIGH",
    "reasonCodes": ["duplicate_document"],
    "duplicateCount": 2,
    "piiRedacted": true
  }
}
```

### `registry.inscription_completed`

```json
{
  "id": "evt_baas_000004",
  "source_system": "baas-qro",
  "schema_version": "1.0",
  "event_type": "registry.inscription_completed",
  "event_category": "registry",
  "occurred_at": "2026-06-06T11:00:00.000Z",
  "recorded_at": "2026-06-06T11:00:01.000Z",
  "status": "completed",
  "correlation_id": "88bfb599-260f-4f4d-9aac-7496e06ef7f4",
  "client_reference": "notary-38-qro",
  "entity_id": "entity_rpp_qro",
  "property_id": "prop_123",
  "folio_real": "FR-123456",
  "registry_matter_id": "RPP-2026-000123",
  "document_id": "doc_789",
  "quantity": 1,
  "unit": "inscription",
  "metadata": {
    "registryOffice": "RPP Queretaro",
    "actType": "compraventa",
    "piiRedacted": true
  }
}
```

### `blockchain.property_minted`

```json
{
  "id": "evt_baas_000005",
  "source_system": "baas-qro",
  "schema_version": "1.0",
  "event_type": "blockchain.property_minted",
  "event_category": "blockchain",
  "occurred_at": "2026-06-06T11:01:00.000Z",
  "recorded_at": "2026-06-06T11:01:01.000Z",
  "status": "succeeded",
  "correlation_id": "88bfb599-260f-4f4d-9aac-7496e06ef7f4",
  "causation_id": "evt_baas_000004",
  "client_reference": "notary-38-qro",
  "blockchain_id": "bc_123",
  "property_id": "prop_123",
  "folio_real": "FR-123456",
  "chaincode_name": "rpp-property",
  "chaincode_function": "MintPropertyNFT",
  "channel_name": "notarychannel",
  "transaction_id": "tx_abc123",
  "block_number": 12345,
  "quantity": 1,
  "unit": "property",
  "metadata": {
    "tokenId": "PROP-123",
    "endorsementPeerCount": 2,
    "piiRedacted": true
  }
}
```

### `registry.certificate_issued`

```json
{
  "id": "evt_baas_000006",
  "source_system": "baas-qro",
  "schema_version": "1.0",
  "event_type": "registry.certificate_issued",
  "event_category": "registry",
  "occurred_at": "2026-06-06T11:10:00.000Z",
  "recorded_at": "2026-06-06T11:10:01.000Z",
  "status": "completed",
  "correlation_id": "88bfb599-260f-4f4d-9aac-7496e06ef7f4",
  "client_reference": "notary-38-qro",
  "entity_id": "entity_rpp_qro",
  "property_id": "prop_123",
  "folio_real": "FR-123456",
  "registry_matter_id": "RPP-2026-000123",
  "certificate_id": "cert_456",
  "quantity": 1,
  "unit": "certificate",
  "metadata": {
    "certificateType": "libertad_gravamen",
    "registryOffice": "RPP Queretaro",
    "piiRedacted": true
  }
}
```

## Final Rule

This contract is for operational events only.

Operational classification and normalization belong to `valteh-revenue-api`.
Economic calculation and dashboard presentation remain in `valteh-revenue-console`.

