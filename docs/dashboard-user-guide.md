# Valteh Revenue Console — User Guide

Use this dashboard to review Valteh's operating economics and maintain clients and costs. Amounts are management
accounting values calculated from plans, usage, and costs. A revenue event does **not** confirm that an invoice was sent
or that a customer deposited funds.

## In this guide

- [General interaction](#general-interaction)
- [Executive Dashboard](#executive-dashboard)
- [Clients](#clients)
- [Costs](#costs)
- [Pricing](#pricing)
- [Usage](#usage)
- [Scenarios](#scenarios)
- [Quick decision guide](#quick-decision-guide)

## General interaction

- Use the left sidebar to change pages and switch between light and dark mode.
- Click a table row before using actions such as Edit, Change, End, or Deactivate.
- Dates use `YYYY-MM-DD`; Anthropic reports use UTC dates.
- Dropdown and chart selections are retained during the browser session where supported.
- If a save says another user changed the record, refresh and review the latest values before retrying.
- Preserve history with effective dates. Use deletion only for a specifically verified accidental record.

## Executive Dashboard

Select a month to review revenue, fixed and variable costs, operating margin, burn rate, break-even usage, active
clients, and service-line performance.

Click **Monthly Revenue** to switch between the total and its fixed-subscription/usage split. Client profitability and
alerts use the selected accounting month.

Revenue is recognized from effective pricing subscriptions and billable usage. It is not a cash-receipts report.

## Clients

The Clients page keeps one durable identity per customer. Pricing subscriptions, usage, revenue calculations, and
external references remain attached to that client.

### Common actions

- **Add client:** enter the client details, initial reusable pricing plan, and optionally an external source reference.
- **Edit client:** correct the name, type, start date, or notes. The Client ID cannot change.
- **Change pricing plan:** select a new plan and effective date. The prior subscription ends the day before the new one
  starts, preserving earlier periods.
- **(De)activate client:** end or resume the client lifecycle without deleting history. Reactivation does not restore a
  pricing plan automatically.
- **Add reference:** map another system's customer or tenant identifier to this client. This is not an API key.

Dedicated ad-hoc pricing plans appear only for their assigned client and cannot be reused for another customer.

### Client Detail

Choose a client and period to inspect usage, revenue, costs, and operating margin. The foldable **Usage Events** and
**Invoices / Revenue Events** tables show the client's complete available history, not only the selected month.

Revenue events are derived from dated subscriptions and usage. If a calculated event is wrong, correct its underlying
subscription or usage record; do not interpret the row as payment confirmation.

The normal workflow has no Delete client action. Deactivate clients that leave and reactivate the same record if they
return.

## Costs

The top of the Costs page summarizes the selected month and year. Expand **Costs Table** to maintain the catalog.

Only `actual` records affect realized costs and margins. `estimate` records remain visible for reference but are
excluded from actual results.

### Choose the correct action

- **Add cost:** create a new cost concept.
- **Edit metadata:** correct descriptive fields, notes, or lifecycle dates without changing the financial terms.
- **Change cost:** create a dated version when quantity, unit cost, currency, unit, basis, frequency, or record type
  changes. Earlier months remain unchanged.
- **End cost:** set the ordinary last effective date.
- **Deactivate:** exclude an invalid record while retaining it for audit.
- **Reactivate:** restore a valid deactivated record when it will not overlap another actual version.

Recognition rules:

| Frequency | Recognition |
| --- | --- |
| `monthly` | Every effective month |
| `annual` | Effective anniversary month |
| `once` | Start-date month only |
| `usage` | Matching event quantity × unit cost |

For usage costs, **Unit** must match the operational event type, for example `saremi.document_validation`. Costs are
reported in MXN; entered USD costs currently use the configured static conversion rate.

There is no general Delete cost action. End normal contracts and deactivate mistaken records.

## Pricing

The page starts with **Pricing Plans**, where you can compare setup, annual and monthly fees, included usage, and unit
prices.

Below the catalog, **Pricing Simulator and Sensitivity** models one potential client:

1. Select a plan.
2. Choose whether to include its one-time setup fee.
3. Enter expected usage, allocated fixed costs, price/cost multipliers, and target margin.
4. Review revenue, costs, operating margin, minimum document price, the operating-margin chart, and sensitivity table.

The simulator is analytical only. Changing its inputs does not edit the plan, client, or database.

## Usage

The page contains Anthropic reporting followed by normalized operational usage.

### Historical Anthropic report

- Shows all usage and cost history already stored in the database.
- **Update history** imports complete UTC days since the latest successful sync and refreshes a small recent overlap.
- Repeated updates are idempotent and do not duplicate usage or costs.
- No date range is needed because the report displays the complete persisted history.

### Live Admin API report

- Select up to 31 days and click **Load Claude report**.
- The result is temporary and is not added to historical storage.
- The latest successful report remains available during the browser session until you load another one.

Both reports support filters for workspace, API key, model, environment, and client. **Group by** controls the chart
and summary table. Use **Usage / Cost** to change the metric and **Daily / Monthly / Yearly** to aggregate the timeline.

Anthropic reports usage by API key but does not provide billed cost at that same level. The dashboard allocates cost
proportionally using matching workspace, model, and usage dimensions. Hover over **Allocated billed cost** for the
current allocation disclaimer.

Use **Assign API keys to clients** to maintain environment and client ownership. The Admin API key always remains on
the server and is never sent to the browser.

### Operational usage

The final table shows normalized events received from Valteh products. If an expected event is missing, verify that its
source status is successful, its type is supported, and its external client reference is mapped on the Clients page.

## Scenarios

Scenarios is a read-only six-month comparison of Base, Pessimistic, and Optimistic cases. The assumptions are displayed
at the top of the page. Use the KPI cards, charts, and monthly table to compare revenue, costs, operating margin, and
active clients.

Scenario results do not modify pricing plans, costs, clients, or forecasts stored elsewhere.

## Quick decision guide

| Situation | Action |
| --- | --- |
| Review current economics | Executive Dashboard → select month |
| Correct a cost description | Costs → Edit metadata |
| Change a cost amount or billing rule | Costs → Change cost |
| End a normal cost contract | Costs → End cost |
| Exclude an invalid cost | Costs → Deactivate |
| Add a customer | Clients → Add client |
| Existing customer changes plan | Clients → Change pricing plan |
| Customer leaves or returns | Clients → (De)activate client |
| Connect a product's tenant/customer ID | Clients → Add reference |
| Compare plan terms | Pricing → Pricing Plans |
| Test pricing assumptions | Pricing → Pricing Simulator and Sensitivity |
| Review long-term Claude usage/cost | Usage → Historical |
| Inspect a temporary recent Claude range | Usage → Live API |
| Compare six-month outlooks | Scenarios |
