# Domain terminology

| Term | Meaning in this repository |
| --- | --- |
| Revenue | Management-accounting amount recognized from contract snapshots and billable usage; not proof of invoice or payment |
| Pricing plan | Versioned catalog offer; may be reusable, informational, retired, or dedicated to one client |
| Subscription | Date-effective client agreement containing authoritative commercial snapshots and overrides |
| Usage event | Operational quantity associated with a client/service; billability and provenance remain explicit |
| Revenue event | Derived recognized amount for a client/service/time, not an invoice line |
| Fixed cost | Active cost independent of usage volume, with monthly/annual/once recurrence |
| Variable cost | Usage-driven cost whose rate is effective on the event date |
| Contribution margin | Unit price minus unit variable cost |
| Break-even usage | Ceiling of fixed costs divided by positive unit contribution margin |
| Display currency | A presentation translation; stored economic facts and original entered amounts are not mutated |
| Provider fact | Raw normalized usage/cost/FX observation from an external provider |
| Allocation | Derived attribution of a provider cost; never a mutation of the provider fact |
| `pending` usage | Source not connected; unknown, not measured zero |
| `available` usage | Production source connected; no events can mean measured zero |
| `demo` usage | Synthetic data excluded from production economics |

