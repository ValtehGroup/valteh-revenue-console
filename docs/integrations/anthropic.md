# Anthropic Admin API

## Components

- `app/integrations/anthropic_admin_api.py`: provider client and normalized report rows.
- `app/domain/anthropic_history_sync.py`: range selection, segmentation, validation, and safe error handling.
- `app/data/anthropic_history_repository.py`: facts, metadata, watermarks, runs, and transactional upserts.
- `app/domain/anthropic_cost_allocation.py`: derived API-key allocation.
- `app/domain/anthropic_realized_costs.py`: billed variable costs, internal/production classification and catalog reconciliation.
- `app/data/anthropic_assignment_repository.py`: date-effective API-key ownership.
- `app/pages/usage.py`: historical and live presentation paths.

Historical sync handles at most 31 days per provider request, excludes the current UTC day, refreshes a configurable overlap (default seven days), and is idempotent. Live results remain in browser-session state and never write history.

Executive Summary, Costs (including annual history), and client profitability use persisted billed costs valued with
the daily Banxico FIX. `production-api-key` remains production pending allocation until manually assigned in Usage;
`dev-api-key` and `sandbox-api-key` are internal Valteh variable costs, never client costs. Unknown keys and unmatched
billed lines remain explicitly unassigned but are included in company totals. Client allocations follow assignment
effective dates. A shared production key cannot be split exactly between clients without SAREMI correlation data.

On successfully synced dates (including measured zero-cost days), billed costs replace variable catalog costs whose
provider is Anthropic or whose key is `ai.claude.document_analysis`. Catalog records remain intact for pricing and
scenarios. Separate local SAREMI preprocessing/validation components are retained. Sync gaps retain catalog rates
and are not interpreted as measured zero. Live report requests alone do not update realized economics.

The Anthropic catalog rows named `Claude Tokens Prod` and `Claude Tokens Dev` are consumption allowances entered as
fixed monthly costs. They remain in the catalog but are excluded from realized costs in all periods to avoid counting
token consumption both as a fixed allowance and as a provider bill. The base Claude subscription remains a separate
fixed expense. Client fixed-cost allocations apply the same reconciliation.

The credential `ANTHROPIC_ADMIN_KEY` is optional until a provider action is requested. Keep it in runtime secrets. Do not log request headers, full API-key IDs in unsafe errors, or any secret value.

Operational commands and recovery guidance are in [Anthropic History Operations](../anthropic-history.md).

