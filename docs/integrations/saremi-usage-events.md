# SAREMI usage-event ingestion

## Purpose and ownership

SAREMI is a production source system with its own read contract. The Revenue platform adapts that contract at the
provider boundary instead of requiring SAREMI to implement the generic operational-event envelope.

The production flow is:

```text
SAREMI -> valteh-revenue-api -> shared revenue database -> valteh-revenue-console
```

`valteh-revenue-api` owns credentials, HTTP calls, pagination, retries, provider-fact persistence, client resolution,
and normalization into `usage_events`. The console reads the shared database and does not call SAREMI directly.

This integration does not consume `/api/internal/ai-usage-events`, does not write Anthropic history, and does not
change Anthropic cost allocation. Anthropic Admin API history remains the source of truth for Claude usage and billed
cost. Any AI summary embedded in a SAREMI verification response may remain in the redacted raw payload for audit, but
must not feed the Anthropic fact tables or economic calculations.

## Current source contract

The contract below reflects SAREMI `main` at commit `d94e2e90d61400b77a524e7599ea9af375ce5c3c`, reviewed on
2026-09-03. It must be verified with an authenticated production fixture before implementation is considered ready.

Preferred endpoint:

```text
GET /api/internal/usage-events
Authorization: Bearer <integration-key>
```

`X-API-Key` is also accepted by the current source implementation. The credential requires the `usage:read` scope.
The credential must remain server-side in `valteh-revenue-api`.

Supported query parameters:

- `cursor`
- `from`
- `to`
- `institution_id`
- `api_key_id`
- `document_type`
- `status`
- `limit` from 1 through 1000, default 100

Current response shape:

```json
{
  "data": [
    {
      "event_id": "ue_<uuid>",
      "verification_id": "ver_<uuid>",
      "institution_id": "inst_<uuid>",
      "institution_name": "Institution name",
      "api_key_id": "key_<uuid>",
      "api_key_name": "Production key",
      "document_type": "INE",
      "operation": "document_verification",
      "status": "verified",
      "created_at": "2026-09-03T10:00:00Z",
      "completed_at": "2026-09-03T10:00:08Z",
      "updated_at": "2026-09-03T10:00:08Z",
      "ai_usage_summary": {
        "call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0
      }
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

The source cursor is based on `(updated_at, id)`. The response is therefore a mutable snapshot/change feed, not an
immutable event log: one `event_id` may be returned again after its status or other fields change.

## Compatibility policy

The provider DTO validates the stable core required for synchronization and accepts additional source fields. New
fields must not break ingestion. The complete redacted source object is retained for audit, while promoted columns
are limited to fields used for identity, synchronization, client resolution, filtering, or normalization.

Rules:

- Preserve `status` exactly as SAREMI sends it. Do not coerce it into the generic `succeeded`/`completed` vocabulary.
- Store unknown statuses and fields safely. Unknown statuses are non-billable and visibly unclassified until a local
  rule is added.
- Treat documented identifiers as opaque strings. Remove known display prefixes only in a focused parsing helper;
  never use unrestricted string replacement.
- Parse timestamps as timezone-aware values and normalize them to UTC without relabeling local time as UTC.
- Upsert a provider fact only when the incoming `updated_at` is newer than the stored source version.
- Preserve the raw provider status separately from locally derived lifecycle and billing decisions.
- Never infer a missing production environment. Missing billing-critical data keeps the fact non-billable.
- Promote a newly added field into a database column only when it is needed for identity, synchronization, filtering,
  client resolution, or a confirmed domain rule. Otherwise retain it in the redacted raw payload.

## Source statuses and local interpretation

SAREMI statuses are intentional product states and remain available for filtering and reporting.

| Source status | Local lifecycle | Terminal for usage | Default billing treatment |
| --- | --- | --- | --- |
| `processing` | in progress | no | non-billable |
| `verified` | completed result | yes | eligible when all other billing guards pass |
| `invalid` | completed result | yes | eligible when all other billing guards pass |
| `inconclusive` | completed result | yes | eligible when all other billing guards pass |
| `manual_review` | review required | no by default | non-billable until the commercial policy is approved |
| `failed` | technical failure | yes | non-billable |
| unknown future value | unclassified | no | non-billable until explicitly supported |

Whether `invalid`, `inconclusive`, or `manual_review` is commercially billable is a Revenue policy, not a source API
validation rule. The initial implementation should use the conservative defaults above and keep the rule centralized
and versioned in the Revenue domain.

## Field ownership and mapping

| SAREMI field | Boundary requirement | Provider-fact use | Normalized Revenue use |
| --- | --- | --- | --- |
| `event_id` | required, non-empty | Stable source snapshot identity | Source provenance; not a price or billing ID |
| `verification_id` | required, non-empty | Verification correlation | Candidate `billable_unit_id` after the one-verification/one-unit rule is confirmed |
| `institution_id` | nullable | Stable SAREMI tenant identity | `(source_system="saremi", external_client_reference=<institution_id>)` |
| `institution_name` | nullable | Diagnostic display | Never used as a durable client key |
| `api_key_id` | nullable | SAREMI client credential attribution | Metadata only; it is not an Anthropic API-key ID |
| `api_key_name` | nullable | Diagnostic display | Metadata only |
| `document_type` | required, non-empty | Source document dimension | Usage metadata/filter |
| `operation` | required, non-empty | Source operation dimension | Expected to be `document_verification`; unknown operations remain unclassified |
| `status` | required, non-empty string | Exact source status | Input to the versioned local lifecycle/billing rule |
| `created_at` | required RFC 3339 timestamp | Source creation time | Audit and latency analysis |
| `completed_at` | nullable RFC 3339 timestamp | Source completion time | Preferred `event_timestamp` for terminal normalized usage |
| `updated_at` | required RFC 3339 timestamp | Source version and cursor order | Upsert guard and incremental watermark |
| `ai_usage_summary` | optional | Optional raw audit data only | Not imported into Anthropic history and not used for cost/revenue |

Locally derived values for an eligible terminal verification are:

```text
source_system = "saremi"
service_code = "saremi"
event_type = "saremi.processed_document"
quantity = 1
unit = "document"
data_origin = "production"
```

`environment`, `is_billable`, and `billable_unit_id` must pass the requirements below; they must not be populated with
optimistic defaults merely to make an event priceable.

## Required additions or confirmations from SAREMI

These requirements describe the information Revenue needs. They do not require SAREMI to adopt Revenue's internal
schema or economic model.

### Blocking for economic activation

1. **Working authenticated endpoint.** `/api/internal/usage-events` must return its documented JSON response after
   authentication. The source owner must correct the current SQL parameter incompatibility before Revenue can use it.
2. **Environment.** Add `environment` to each event and support the existing source values, currently `production`
   and `test`. Revenue maps `test` to `sandbox` and preserves the original value in source metadata.
3. **Stable billable-unit rule.** Confirm in writing that one `verification_id` represents one logical processed
   document for billing, including retry and resubmission behavior. If it does not, expose a separate stable
   `billable_unit_id`.
4. **Mutation semantics.** Confirm which statuses may transition after `completed_at`, especially
   `manual_review`, and whether deleted/corrected verifications remain exportable with a newer `updated_at`.
5. **Client identity.** Confirm that `institution_id` is immutable and retained after institution deactivation. A
   source-side `client_reference_id` may be added when callers already supply a more appropriate commercial identity.

Until items 1 through 5 are satisfied and reconciled, provider facts may be imported for observation but must not
change `usage_data_status` to `available` or generate usage revenue.

### Required operational documentation

- Production base URL and network-access requirements.
- Credential creation, delivery, rotation, expiry, revocation, and `usage:read` scope behavior.
- `401`, `403`, `429`, and `5xx` response behavior, including any retry guidance.
- Rate limits and recommended polling interval.
- Historical retention and earliest available `from` date.
- Whether cursors expire and whether a cursor is tied to the original filters.
- Maximum supported backfill window.
- Timestamp guarantee: RFC 3339 UTC with timezone information.
- Status transition table and correction/deletion behavior.

### Useful non-blocking additions

- `client_reference_id` when SAREMI callers provide their own stable reference.
- `document_hash` when already redacted and safe, for reconciliation only.
- `retry_of_verification_id` or `correlation_id` for operational traceability.
- `status_reason_code` for sanitized failure or review categorization.
- `schema_version` for explicit source-contract evolution.

Revenue must remain forward-compatible even if these optional fields are absent.

## Persistence and synchronization requirements

SAREMI provider facts should be stored separately from generic immutable operational events. A focused schema avoids
changing BAAS/RPP ingestion semantics and supports SAREMI updates cleanly.

Minimum durable state:

- One provider-fact row per SAREMI `event_id`, including `source_updated_at` and a redacted raw payload.
- One independent synchronization state for the `saremi.usage_events` stream.
- Cursor persisted transactionally after each successfully stored page.
- Completed-run watermark based on the largest `updated_at` seen.
- Configurable overlap when restarting from the watermark.
- Sync-run audit with start/end time, pages, received, inserted, updated, unchanged, invalid, unresolved, and failed
  counts.

Repeated runs must be idempotent. A crash must be resumable without losing a page. An older snapshot must never
overwrite a newer fact. Client mappings added later must allow stored unresolved facts to be reprocessed without
contacting SAREMI again.

## Client mapping and billing guards

Use the stable institution identifier, not institution name or API-key ID:

```text
(source_system="saremi", external_client_reference="inst_<uuid>") -> Revenue client_id
```

Unmapped institutions remain stored and visible as unresolved. They never produce normalized billable usage.

A provider fact may create or update one `saremi.processed_document` usage event only when all of these are true:

- The source operation is an explicitly supported document-verification operation.
- The source status is terminal and eligible under the versioned local policy.
- `completed_at` is present.
- The source environment is known and maps to `production`.
- The institution has an enabled client mapping.
- A stable billable unit is available.
- The event is not demo data and has not already produced the same billable unit.

Source facts that fail a guard remain auditable with a clear local classification reason.

## Administrative endpoint fallback

`GET /admin/verifications` may be used temporarily when the internal endpoint is unavailable, but only behind the
same provider-client interface. The fallback requires an approved BAAS machine identity, selects only safe fields,
filters production data explicitly, uses overlapping rescans plus upserts, and never persists extracted document
content, checks, filenames, paths, IP addresses, or other unnecessary personal data.

The fallback is not the long-term contract because it uses page/offset pagination, filters by `created_at` rather than
`updated_at`, returns a broader administrative payload, and depends on BAAS user-token lifecycle. It cannot supply
SAREMI AI-call events.

## Rollout acceptance criteria

- Authenticated contract fixture validates against the provider DTO.
- New optional fields do not break ingestion.
- Unknown statuses are stored but remain non-billable.
- `processing -> terminal` updates the provider fact and produces at most one normalized usage event.
- Replaying a page or backfill creates no duplicates.
- Test/sandbox, failed, unmapped, and billing-incomplete facts create no revenue.
- Daily counts reconcile by institution, document type, and source status.
- Cursor/watermark state does not advance when page persistence fails.
- No credential or disallowed SAREMI payload field reaches logs, URLs, browser state, or Console tables.
- Anthropic history and allocation tests remain unchanged and passing.
