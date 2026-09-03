# SAREMI

The repository contains the 2026 SAREMI pricing catalog, client contract snapshots, revenue/cost rules, and the
normalized billable event understood by the economic engine. SAREMI now exposes a production-specific usage-event
contract, but this repository does not yet contain its production consumer; `app/integrations/saremi_api.py` remains a
mock adapter. Production HTTP ingestion belongs in `valteh-revenue-api`.

The canonical billable event is `saremi.processed_document`: one logical document reaching a usable terminal result. It is not a page, validation call, token count, internal retry, or failed upload. Production billing requires `is_billable=true`, a production environment, and a stable `billable_unit_id` for deduplication.

Usage state is explicit:

- `pending`: unknown because the source is not connected;
- `available`: source connected, so an empty cycle can be measured zero;
- `demo`: synthetic and excluded from production economics.

SAREMI source statuses (`processing`, `verified`, `invalid`, `inconclusive`, `manual_review`, and `failed`) are
preserved exactly. Revenue derives lifecycle and billability separately so a new provider status cannot accidentally
create revenue.

Anthropic usage and billed cost continue to come from the existing Anthropic Admin API integration. SAREMI's
`/api/internal/ai-usage-events` endpoint is outside the scope of this integration.

The provider contract, missing-field requirements, mapping, and rollout guards are in
[SAREMI Usage-Event Ingestion](saremi-usage-events.md). Commercial rules are in
[SAREMI Pricing and Future Usage](../saremi-pricing-and-usage.md).
