# Anime Discovery — next generation

This directory is the clean-slate **implementation home**, not an active runtime. The authoritative handoff and safety rules are in the root [development.md](../../development.md), section **Architecture handoff — clean-slate next generation (2026-10-22)**.

## Working principles

- One versioned canonical release-record **contract**, populated progressively by bounded stages.
- Small explicit components: webhook intake, verified identity, acquisition, staging, human evaluation, Keep/Sonarr export, and event history.
- A small coordinator dispatches existing durable SQLite jobs; **no dynamic hooks or plugin registry**.
- Each component owns its fields and may change internally without editing unrelated components.
- Build a **read-only record assembler** and contract tests before implementing new write paths.
- Reuse tested legacy providers, identity mapping, media verification, Jellyfin NFO logic and adapters. Do not guess seasons or episode equivalence.
- Existing `src/legacy/` runs unchanged until a separate audited, approved cutover.

## Not yet implemented

This README creates no new runtime, migration, database schema, staging directory, service, or deployment. The record schema, components and compatibility tests are subsequent scoped changes. No file here should be run in production merely because it exists.

## Proposed structure (future, not directories required now)

```text
src/nextgen/
  contracts/       # Versioned ReleaseRecord and per-stage validated views
  components/      # Intake, identity, acquisition, staging, evaluation, export
  orchestration/   # Thin job handoff coordination using existing daemon_jobs
  observability/   # Stable trace IDs and durable event history
  tests/           # Contract, behavior-equivalence and crash/restart tests
```
