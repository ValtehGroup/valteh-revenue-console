# Valteh Revenue Console — Costs and Clients User Guide

This guide explains how dashboard users maintain Costs and Clients, what each
table column means, how historical changes are preserved, and which operations
are intentionally unavailable.

## General interaction

- Click anywhere on a table row to select it. The highlighted row is the active
  record for the action buttons above the table.
- Filters and period selections are retained while navigating between tabs in
  the same browser session.
- Dates use `YYYY-MM-DD` format.
- Save operations reject stale data. If another user changed the same record,
  refresh the page, review the latest values, and try again.
- Use lifecycle dates and versioning for normal business changes. Deactivation
  is reserved for records that should not participate in calculations.

## Costs

### What the Costs tab represents

The Costs dashboard reports realized operating costs in MXN. The Costs Table is
the maintained catalog behind those calculations. A cost can have multiple
dated versions so past months keep the values that were valid at that time.

Only records with `Record Type = actual` participate in realized costs and
margins. Budget and estimate records remain visible in the table but do not
affect actual financial results.

### Add a cost

1. Open the **Costs** tab and expand **Costs Table** if necessary.
2. Click **Add cost**.
3. Enter the descriptive fields: Name, Provider, Category, and Service Line.
4. Select the Charge Basis and Billing Frequency.
5. Enter Quantity, Unit Cost, Currency, and Unit.
6. Select the Record Type.
7. Enter the Start Date and, if known, an optional End Date.
8. Add Notes that explain the source or assumption.
9. Click **Save**.

The dashboard derives Cost Type from Billing Frequency:

- `usage` frequency creates a variable cost.
- `monthly`, `annual`, or `once` creates a fixed cost.

The generated Cost Key is internal and hidden from the table. It identifies the
same business cost across historical versions.

### Modify a cost

Select the applicable row and choose the action that matches the change.

#### Edit metadata

Use **Edit metadata** to correct:

- Name
- Provider
- Category
- Service Line
- Start Date or End Date
- Notes

Start and End Date edits are lifecycle corrections and can change which months
include the record. They cannot create an overlap with another active actual
version of the same cost.

Do not use Edit metadata to overwrite Quantity, Unit Cost, Currency, Unit,
Billing Frequency, Charge Basis, or Record Type. Those fields affect financial
meaning and require a new version.

#### Change cost

Use **Change cost** when the amount or financial configuration changes.

1. Select the current version.
2. Click **Change cost**.
3. Enter **Effective from**.
4. Enter the new Quantity, Unit Cost, Currency, Unit, Charge Basis, Billing
   Frequency, and Record Type.
5. Save.

The dashboard atomically:

- ends the selected version one day before the effective date;
- creates a new row with a new ID and the same internal Cost Key; and
- leaves all earlier months unchanged.

The effective date must be after the selected version's Start Date and must fall
within its current lifecycle. Overlapping active actual versions are rejected.

#### End cost

Use **End cost** for an ordinary cancellation or known end of service. The row
remains enabled and continues to appear in historical calculations through its
End Date. After that date its displayed status becomes **Ended**.

#### Deactivate and Reactivate

Use **Deactivate** only for a mistaken or invalid record. Deactivation keeps the
row for audit purposes but immediately excludes it from economic calculations,
regardless of its dates.

Use **Reactivate** to restore a deactivated row without changing its dates.
Reactivation is rejected if it would overlap another enabled actual version. If
the restored row already has a past End Date, its table status returns to
**Ended**, not Active.

### What users cannot do with costs

- The dashboard has no general Delete action. Normal history must be ended or
  deactivated, not erased. Permanent deletion is an administrator-only cleanup
  for a specifically verified accidental test record.
- A historical financial value cannot be overwritten through Edit metadata.
  Use Change cost to create a new dated version.
- Active actual versions of the same Cost Key cannot overlap.
- Variable costs cannot use monthly, annual, or once frequency.
- Fixed costs cannot use usage frequency.
- Negative Quantity or Unit Cost values are not accepted.
- The dashboard currently accepts MXN and USD only. USD uses the configured
  temporary rate of `1 USD = 18 MXN`; it is not a historical market FX rate.

### Cost fields and table columns

| Field or column | Meaning |
| --- | --- |
| ID | Four-digit identifier for one specific stored version, such as `0015`. A changed version receives a new ID. |
| Name | Human-readable cost description. |
| Status | **Active** is enabled and not past its End Date; **Ended** is enabled but past its End Date; **Inactive** is deactivated. |
| Category | Reporting grouping such as Software, Infrastructure, People, or AI. |
| Service Line | Product or shared area receiving the cost, such as SAREMI, Graphos, BaaS, SIGEN, or Shared. |
| Provider | Supplier or internal provider responsible for the cost. |
| Cost Type | Derived classification: fixed or variable. |
| Frequency | Recognition rule: monthly, annual, usage, or once. |
| Charge Basis | `flat`, `per_user`, or `usage`; describes what Quantity represents. |
| Quantity | Number of configured units. Displayed as an integer in the table. |
| Unit | Measurement unit. For a usage cost, this must match the usage event type, such as `saremi.document_validation`. |
| Unit Cost | Cost of one unit, displayed in the entered Currency with two decimals. |
| Currency | Original entered currency, currently MXN or USD. |
| Base Amount | `Quantity × Unit Cost`, converted and displayed in MXN. This is the configured amount, not always the amount recognized in every month. |
| Start Date | First date on which this version can apply. |
| End Date | Last date on which this version can apply; blank means open-ended. |
| Record Type | `actual` affects realized results; `budget` and `estimate` are informational. |
| Updated At | UTC audit timestamp of the most recent change. |
| Notes | Source, rationale, assumptions, or operational context. |

Recognition details:

- Monthly fixed: recognizes the Base Amount in every effective month.
- Annual fixed: recognizes the Base Amount in the anniversary month while the
  record remains effective.
- Once: recognizes the Base Amount only in the Start Date month.
- Usage: recognizes recorded event quantity multiplied by the applicable unit
  rate; the configured table Quantity is not the realized event volume.

### Cost examples

#### Example 1: Microsoft subscription price changes

Assume four users cost `8 USD` each per month beginning July 1:

- Charge Basis: `per_user`
- Quantity: `4`
- Unit Cost: `8.00`
- Currency: `USD`
- Unit: `user`
- Frequency: `monthly`
- Record Type: `actual`
- Start Date: `2026-07-01`

The Base Amount is `4 × 8 × 18 = 576 MXN`.

If the provider raises the price to `10 USD` beginning September 1, select the
current row and use **Change cost** with Effective from `2026-09-01`. The old
version ends August 31 and the new version begins September 1. July and August
remain `576 MXN`; September onward becomes `720 MXN`.

#### Example 2: AI document-processing usage rate

To charge `0.95 MXN` per processed document:

- Charge Basis: `usage`
- Quantity: `1`
- Unit Cost: `0.95`
- Currency: `MXN`
- Unit: `saremi.document_validation`
- Frequency: `usage`
- Record Type: `actual`

If 1,000 matching usage events are recorded in a month, the realized cost is
`1,000 × 0.95 = 950 MXN`.

## Clients

### What the Clients tab represents

One client record represents one durable customer identity. Pricing plans are
stored as dated subscriptions beneath that identity. Usage, revenue, plan
changes, and lifecycle history remain attached to the same client ID.

Real clients receive IDs such as `client_0001`. Designated dashboard test
clients use IDs such as `test_0002`.

### Add a client

1. Open the **Clients** tab.
2. Click **Add client**.
3. Enter Name, Client Type, Start Date, and optional Notes.
4. Select the initial Pricing Plan. Options come from the maintained Pricing
   Plans catalog.
5. Optionally add a Source System and External Client Reference together.
6. Click **Save**.

The client and initial pricing-plan subscription are saved in one transaction.
The subscription starts on the client's Start Date. A new real-client ID is
generated automatically and cannot be edited.

### Modify a client

#### Edit client

Use **Edit client** to change Name, Client Type, Start Date, or Notes.

The Client ID is permanent. A Start Date cannot be moved later than existing
subscription, usage, or revenue history, and cannot be after the End Date.

#### Change pricing plan

Use **Change pricing plan** for an active client moving from one commercial plan
to another.

1. Select the client row.
2. Click **Change pricing plan**.
3. Select the new plan.
4. Enter Effective from.
5. Save.

The dashboard atomically ends the applicable prior subscription one day before
the effective date and creates the new subscription. Client ID and all prior
subscription, usage, revenue, and margin history are preserved. The effective
date must be after existing or scheduled subscription Start Dates, and the same
currently effective plan cannot be selected again.

#### Deactivate and Reactivate client

The **(De)activate client** button changes behavior based on Client Status.

- For an active client, enter an effective deactivation date. The client End
  Date is set, active subscriptions are ended, and status becomes Inactive.
- For an inactive client, the action reactivates the client and clears its End
  Date.

Reactivation does not recreate or reactivate a pricing subscription. After
reactivation, use **Change pricing plan** to assign the appropriate new plan if
needed.

Deactivation retains all historical usage, revenue, subscriptions, and external
references.

#### External references

External references map a client identity used by another system to the local
client record.

- **Add reference** creates a mapping for a Source System and External Client
  Reference.
- **Deactivate reference** disables the mapping but retains it for audit.

Example: if SAREMI sends `client_reference = notaria-38-qro`, use:

- Source System: `saremi`
- External Client Reference: `notaria-38-qro`

This value is a customer, tenant, or organization identifier. It is not an API
key or credential. The same external value may be used by different source
systems, but the `(Source System, External Client Reference)` pair must be
unique.

### What users cannot do with clients

- Client ID cannot be edited or reused for another customer.
- A plan change does not create a second client; the original client must be
  retained.
- The dashboard has no general Delete client action. Deactivation is the normal
  lifecycle operation. Permanent deletion is administrator-only cleanup for a
  specifically verified accidental record with no business history.
- Inactive clients cannot change pricing plan until they are reactivated.
- Reactivation does not restore an old plan automatically.
- Pricing-plan definitions cannot be edited from the Clients table; they come
  from the Pricing Plans catalog.
- Existing usage, revenue, or subscription history cannot be silently deleted
  through Edit client or Deactivate.

### Client table columns

| Column | Meaning |
| --- | --- |
| Client ID | Permanent public identifier, such as `client_0001` or `test_0002`. |
| Client Name | Customer's display name. |
| Client Type | Business classification such as notary or enterprise. |
| Client Status | Current lifecycle status: active or inactive. |
| Start Date | Beginning of the client relationship. |
| End Date | Effective end of the relationship; blank for an active open-ended client. |
| Pricing Plan | Plan effective for the dashboard's current reporting month, or **No active plan**. |
| Monthly Revenue | Subscription plus billable usage revenue for the current reporting month. |
| Monthly Usage | Sum of the client's usage quantities for the current reporting month. |
| Monthly Variable Cost | Usage-driven costs attributed to the client for the month. |
| Allocated Fixed Cost | Equal share of the month's fixed costs allocated among economically active clients. |
| Operating Margin | Monthly Revenue minus Monthly Variable Cost and Allocated Fixed Cost. |
| Operating Margin Percentage | Operating Margin divided by Monthly Revenue; zero when revenue is zero. |
| Alerts | Inactive, No active plan, No usage recorded, Low margin, High usage, or OK. |
| Created At | UTC audit timestamp for creation. |
| Updated At | UTC audit timestamp for the latest client change. |
| Notes | Internal operational or commercial context. |

The Clients table economics use the latest dashboard reporting month. Use the
Client Detail Period selector to inspect a particular month.

### Client Detail behavior

- Client and Period selectors are independent of the Executive Dashboard month.
- Usage, Revenue, and Cost by Service charts use the selected Period.
- Historical Usage and Margin trends cover the complete available timeline.
- Foldable Usage Events and Invoices / Revenue Events sections show the client's
  complete available history, not only the selected Period.

### Client examples

#### Example 1: Pilot client moves to SIGEN Go

Notaria 38 remains `client_0001` throughout the relationship:

1. Its Pilot subscription runs through `2026-08-31`.
2. Select Notaria 38 and click **Change pricing plan**.
3. Select **SIGEN Go** with Effective from `2026-09-01`.
4. Save.

The dashboard ends Pilot on August 31 and starts SIGEN Go on September 1. August
reports continue using Pilot, September reports use SIGEN Go, and all history
remains attached to `client_0001`.

#### Example 2: Client pauses and later returns

1. Deactivate the active client with the last service date.
2. Historical data remains available in Client Detail.
3. When the client returns, select the inactive row and use **(De)activate
   client** to reactivate it.
4. Use **Change pricing plan** to assign a new plan and effective date.

Do not add the returning customer as a new client.

## Quick decision guide

| Situation | Correct action |
| --- | --- |
| Correct a cost name or provider | Edit metadata |
| Cost price, quantity, frequency, unit, or currency changes | Change cost |
| Cost contract normally ends | End cost |
| Cost row was mistaken or invalid | Deactivate |
| Restore a valid deactivated cost | Reactivate |
| Add a new customer | Add client |
| Correct client name, type, Start Date, or Notes | Edit client |
| Existing client changes commercial plan | Change pricing plan |
| Client relationship ends | (De)activate client → Deactivate |
| Inactive client returns | (De)activate client → Reactivate, then assign a plan |
| Connect an external product's tenant ID | Add reference |

