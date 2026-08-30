# Anthropic Admin API

## Components

- `app/integrations/anthropic_admin_api.py`: provider client and normalized report rows.
- `app/domain/anthropic_history_sync.py`: range selection, segmentation, validation, and safe error handling.
- `app/data/anthropic_history_repository.py`: facts, metadata, watermarks, runs, and transactional upserts.
- `app/domain/anthropic_cost_allocation.py`: derived API-key allocation.
- `app/data/anthropic_assignment_repository.py`: date-effective API-key ownership.
- `app/pages/usage.py`: historical and live presentation paths.

Historical sync handles at most 31 days per provider request, excludes the current UTC day, refreshes a configurable overlap (default seven days), and is idempotent. Live results remain in browser-session state and never write history.

The credential `ANTHROPIC_ADMIN_KEY` is optional until a provider action is requested. Keep it in runtime secrets. Do not log request headers, full API-key IDs in unsafe errors, or any secret value.

Operational commands and recovery guidance are in [Anthropic History Operations](../anthropic-history.md).

