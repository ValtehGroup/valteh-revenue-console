# Integration overview

| Integration | Current implementation | Important boundary |
| --- | --- | --- |
| Anthropic Admin API | Real server-side HTTP adapter, live reports, durable history sync | Provider facts and derived allocation stay separate |
| Banxico SIE | Real explicit-sync adapter for USD/MXN FIX `SF43718` | No provider calls during startup/rendering |
| SAREMI | Production provider contract documented; source adapter and sync are pending | Preserve source statuses/facts; `valteh-revenue-api` owns ingestion and normalization |
| Graphos, Blockchain, LLM usage | Mock adapters returning sample usage events | Do not treat as production telemetry |
| Platform API | Mock adapter returning sample client records | Do not treat as a production client source |

Real adapters validate provider responses, use timeouts, return safe errors, and never expose credentials in URLs or UI state. Mock adapters are placeholders, not evidence of a live connection. Provider-independent orchestration belongs in `app/domain/`; durable state belongs in `app/data/`.
