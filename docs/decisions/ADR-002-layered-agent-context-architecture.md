# ADR-002: Layered agent context architecture

- Status: Accepted
- Date: 2026-08-30

## Context

A growing codebase needs enough context for Codex, Claude, and similar tools without loading a large, stale, vendor-specific `context.md` on every task. Detailed docs also need clear ownership and must not compete with executable behavior as the source of truth.

## Decision

Use a vendor-neutral layered context system:

1. `AGENTS.md` is the canonical short entry point and lists non-negotiable boundaries.
2. Vendor files such as `CLAUDE.md` are thin wrappers that import or point to the canonical guide.
3. `docs/INDEX.md` routes agents to small task-specific context sets.
4. Modular documents under architecture, domain, data, integrations, development, and decisions explain current intent and constraints.
5. Code, tests, and migrations remain authoritative for runtime behavior and schema; live file discovery is preferred over a generated repository inventory.

Context is loaded progressively. Documents link to implementation and tests instead of copying large code blocks or mutable values. Speculative integrations and unapproved roadmap ideas stay outside the context system. Secrets, raw PII, and credentials are forbidden in agent context.

## Consequences

- Agents spend less context on unrelated material and can navigate by task.
- Knowledge can be updated near the affected concern.
- A small amount of documentation maintenance is required when behavior or architectural intent changes.
- File listings and symbols are discovered from the current checkout, avoiding a duplicated generated inventory.
