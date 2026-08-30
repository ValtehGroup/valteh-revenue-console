# SAREMI

The repository contains the 2026 SAREMI pricing catalog, client contract snapshots, revenue/cost rules, and the normalized billable event understood by the economic engine. It does not contain a production SAREMI HTTP ingestion client; `app/integrations/saremi_api.py` is a mock adapter.

The canonical billable event is `saremi.processed_document`: one logical document reaching a usable terminal result. It is not a page, validation call, token count, internal retry, or failed upload. Production billing requires `is_billable=true`, a production environment, and a stable `billable_unit_id` for deduplication.

Usage state is explicit:

- `pending`: unknown because the source is not connected;
- `available`: source connected, so an empty cycle can be measured zero;
- `demo`: synthetic and excluded from production economics.

Anthropic aggregate facts do not provide exact document attribution. Any production source pipeline must preserve document/API-key/model/token correlation telemetry; unmatched cost stays explicit.

Detailed commercial rules are in [SAREMI Pricing and Future Usage](../saremi-pricing-and-usage.md).
