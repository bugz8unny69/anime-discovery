# Anime Discovery — NextGen development handoff

> **Authoritative architecture decision: 2026-10-22.** NextGen is built fresh in `src/nextgen/`. There is **no migration**, compatibility bridge, legacy SQLite reader or transitional data assembler. Legacy `src/legacy/` is reference material for domain lessons and regression tests only.
>
> **Operational guardrails:** Draft work on branches/PRs; do not merge, deploy, restart services, change production databases, acquire/delete torrents, or touch user media without explicit authorization. Use `NextGen` as the PR target for new NextGen work. Keep `develop` for the existing legacy application. Current policy: include offline tests but do not execute them or CI; record tests as unrun.

## SQLite migration and maintenance follow-up — 2026-10-22

The migration/maintenance library builds on draft configuration PR #101; that PR
is not assumed merged. The follow-up branch contains its prerequisite commits
and targets NextGen. Review the prerequisite independently before merging either.

Implemented: version-aware SQLite v1–v6 upgrade preview/apply, verified pre-upgrade
SQLite backup, per-step validation/rollback, a durable cross-process maintenance
admission gate, and an admitted existing-database connection helper. No schema
shape changes or v7 migration. Published 001–006 remain unchanged. See
[the migration/maintenance contract](src/nextgen/storage/MIGRATIONS.md).

All future runtime DB users and entire job attempts must participate in the gate.
A request blocks new work while admitted work finishes; queued job states are
preserved. No automatic resume after success/failure/crash: compatible process
readiness and explicit completion are required. No supervisor, management API,
ADM command or coordinator runtime is implemented by these libraries.

Remaining coordinator preparation: async handler/outcome contract, bounded
claim/dispatch and cancellation semantics, lease/retry recovery policy and
management-to-runtime readiness integration. Keep the API in its own process.
Tests are included but unexecuted; source/syntax/diff review only, no CI or SQL.

## Current diagnostic implementation — PR #100, 2026-10-22

The PR #100 branch implements shared messages.py event/state catalogs and a
translation-ready renderer, history.py transaction-bound audit writers, and
SQLite schema v6 (004_diagnostic_components.sql, 005_job_statuses.sql,
006_api_diagnostics.sql and fresh-schema changes).
Existing settings/logging and reason registry are reused. Logging now resolves
static English copy, derives correlation from IDs, and emits bounded safe
exception summaries. Runtime-only OPERATION_FAILED does not add a job state.

Mandatory policy: [every diagnostic marker/error needs human-readable copy](src/nextgen/HUMAN_READABLE_MESSAGES.md).
Job states/activity: [JOB_STATUSES.md](src/nextgen/JOB_STATUSES.md).
Contract/API: [DIAGNOSTIC_CONTRACT.md](src/nextgen/DIAGNOSTIC_CONTRACT.md).
Schema/version authority: [SCHEMA_POLICY.md](src/nextgen/storage/SCHEMA_POLICY.md).
These documents supersede older planning snapshots below where status differs.
Use GitHub as the authority for PR #100 publication/merge status. Source review and AST
syntax checks only; offline tests are included but unexecuted, with no CI runs.

Next component: coordinator claims/routing, leases and stale-owner fencing,
retry/backoff/exhaustion decisions, atomic completion/successor creation, and
offline lifecycle/concurrency/recovery cases. Diagnostic writers do not enforce
those transitions. No coordinator loop, supervisor reload distribution, journal
service integration, dashboard API, deployment or legacy modifications are
implemented by this diagnostics PR.

## Management process boundary and configuration readiness review

Agreed: the management API runs in a separate process, using diagnostic
component api. ADM and dashboard are clients of that API. The API owns
management authentication/authorization and invokes shared services; the
service account owns its writable files/directories. The coordinator only
manages independent jobs and a small async pause/drain/resume/shutdown control
interface. It does not host the public management API, persist settings or run
schema migrations as ordinary jobs. Supervisor owns process management later.

Configuration follow-up: configuration_schema.py and configuration.py implement
an explicit v0→v1 NextGen logging-file conversion, validated versioned snapshots,
revision-checked atomic service-owned persistence and migration preview/backups.
See [CONFIGURATION.md](src/nextgen/CONFIGURATION.md) for the API/library contract.
Fields explicitly declare next_operation or restart behavior. Each new job
attempt/API request reads current settings once; running operations keep their
snapshot. Restart fields stay pinned to process startup values. Process-level
ports/concurrency/database changes require explicit restart, not a live reload
broadcast. This library does not implement a credential store, SQLite runner,
management authentication/transport or automatic runtime application.

Next work order after configuration-library review: implement the SQLite
migration runner and cross-process maintenance/readiness contract; define the async job-handler
input/outcome/recovery interface. Implement the separate authenticated
management API against those services, then the coordinator against its job
and control contracts. These contracts can be defined together without
embedding the API in the coordinator. No hook/plugin system is introduced.
Concurrent jobs for the same anime are allowed: no blanket per-anime
serialization. Libraries own shared provider pacing and exact-resource
acquisition gates, returning structured defer/hold/duplicate outcomes. The
async coordinator applies bounded overall concurrency and registered handler
execution modes; blocking operations can use threads. No process per job is
required without a concrete isolation/CPU need.
The full dashboard, supervisor, provider and acquisition implementations remain
later work. Configuration/management feature changes belong in focused PRs,
not extensions that silently enlarge the diagnostics implementation.

## NextGen settings and diagnostics foundation — 2026-10-22

Work in branch `nextgen/config-diagnostics-20261022`. Before developing `coordinator`, use the independent `src/nextgen/settings.py` and `src/nextgen/diagnostics.py` foundation. Defaults: logging INFO; supported levels TRACE, DEBUG, INFO, WARNING, ERROR and CRITICAL. Optional validated component overrides for supervisor, intake, coordinator, identity and acquisition. TRACE is custom level 5; higher verbosity NEVER relaxes redaction. The standard library logger writes sanitized, bounded correlation records to stderr/journald, with event/job IDs, attempt, elapsed time and reason code when available. SQLite `event_history` and `job_history` remain separate durable state histories, and coordinator code must persist transitions atomically when implemented.

Configuration currently loads strict JSON into immutable settings wrappers; hot reload, supervisor distribution, dashboard UI, external services, live workers and persistence of configuration are NOT implemented. Unknown keys and unsupported levels fail validation. Never log raw webhook bodies, provider responses, torrent secrets or credentials. Legacy diagnostics (merged PR #67) and legacy settings schema inform this fresh NextGen module only; no dependency on `src/legacy`. Offline tests are committed but deliberately not run yet, and CI remains disabled. Do not merge/deploy without explicit instruction.

## What is canonical

**Series schema, not processing state.** NextGen uses one versioned `AnimeSeries v2` schema (`src/nextgen/schema/anime_series.py`; detailed RFC at `src/nextgen/schema/README.md`). The series describes **the anime and its episodes**. It MUST NOT include webhook notification IDs, traces, GUIDs, source release names, job IDs, retries, acquisition, staging, evaluation, or export status. That information lives in independent durable operational records connected to the series after identification.

The identified series's required fields are:
- `anime.anidb_id`: positive AniDB anime ID (anime and sequel/cour identity).
- `anime.tvdb_series_id`: positive verified TVDB **series** ID for Sonarr; mandatory for functional downstream integration.
- `anime.title`: nonblank **identified anime title**, not the original release name.
- `schema_version`: exactly `2` in the V2 validator.

The `anime.tvdb_series_id` link is **mandatory**, because the full pipeline needs Sonarr's TVDB series identity. AniDB remains authoritative for anime and episode identities; this requirement does not make TVDB episode/season placement mandatory. `episodes` may be omitted or empty; missing normalizes to `[]`. **Every populated episode** MUST have an exact verified positive `anidb_episode_id` (for Shoko and episode-specific operations). An empty list is a series-only identity, **not** proof a batch contains zero episodes or that episode-level identification is finished.

Other series descriptors (alternative/original titles, year, anime type, AniDB episode display numbers, episode title/type, optional `episodes[].tvdb_placement` and `attributes`) are nullable or optional. TVDB *episode-level* IDs and per-episode TVDB season/episode mapping **are not hard AniDB series-identification requirements**. Known placement is represented as `{season, episode}` inside the episode, with season 0 permitted for specials. AniDB episode numbering MAY be continuous or nonstandard. Never infer TVDB season from AniDB ordinal, default unknown to S01/E01, or conflate separately cataloged AniDB sequel entries under one TVDB series.

Every published series MUST satisfy a uniform, machine-checkable schema; optional fields normalize to null/empty object to spare future consumers missing-key crashes. Field docs track meaning, reason, owner, availability, and origin. Breaking changes require explicit schema versioning and permanent offline fixture tests. Structured optional attributes never override the core named fields.

### RFC-IDENTITY-001: mandatory completion gate

**This gate is at the END of anime-series identification, not at the webhook.** Series identification and episode/release identification are different: the former MAY succeed without any identified episodes, but that alone MUST NOT authorize episode-specific downstream actions.

- The identification component gathers information in its own *incomplete* work state. An unrecognized AniDB anime is **not** a completed series. An absent TVDB series link is **not** a valid completed AnimeSeries identity. An empty episode array **may** be a valid identified anime series, but MUST NOT be interpreted as completed episode identification or release coverage.
- Before publishing an identified anime series, the identity component MUST validate the candidate via `AnimeSeries.from_dict` (or equivalent V2 validation). Only a passing result may be recorded as the series identity. A populated episode additionally requires independently verified AniDB episode evidence. Numeric shape validation cannot prove an ID came from AniDB.
- Failed series schema validation MUST prevent completed anime-series identification; missing/unverified episode identities MUST separately block episode-specific acquisition completion, Shoko linking and Sonarr episode import. Persist a reason-coded, traceable **INCOMPLETE_IDENTITY** or **INVALID_IDENTITY** outcome in operational job history. The identity work MAY retry when information improves, or enter review. A failed candidate is a normal per-item outcome; it MUST NOT crash workers or lose the original webhook notification.
- A series identity, even with no identified episodes, can be read without repeated anime-series identification by downstream components. Components still enforce their own **separate**, integration-specific prerequisites (e.g. exact TVDB episode placement before the NFO/episode import operation that needs it, file ownership/path verification at use time). The RFC is not authorization to acquire or export.

## Job architecture handoff — agreed 2026-10-22 (follow-up to merged PR #94)

**Current work:** dedicated jobs-table SQLite follow-up on branch `nextgen/dedicated-jobs-20261022`, targeting `NextGen`. PR #94 already merged the six-table SQLite foundation and AnimeSeries v2 remains unchanged.

**Agreed design:** Webhook intake and the worker/coordinator are different Linux processes (different PIDs). Intake durably writes the original webhook observation and an initial `jobs` row in a single SQLite transaction, then acknowledges. The worker/coordinator polls `jobs`, atomically leases eligible work, dispatches by `kind`, records outcomes and recovers expired leases. Components can request new independent jobs.

**No parent/child relationship:** `created_by_job_id` is nullable provenance only, not a dependency, hierarchy, sibling relation, execution ordering, or cascading-lifecycle rule. `event_id` is also nullable on jobs for work without a webhook. Every job has an independent lifecycle. Completing a job and creating a follow-up job must be an atomic SQLite transaction when both operations are required.

**Job history:** `job_history` records independent job transitions, attempts, handoffs and reason-coded failures; it is separate from webhook `event_history`. A future coordinator must insert the history record together with the associated job state change.\n\n**SQLite v1 jobs columns:** job_id, nullable event_id, nullable created_by_job_id, kind, payload_json, state (PENDING/RUNNING/RETRY_WAIT/NEEDS_REVIEW/DONE), available_at_ms, attempt_count, nullable lease_token, nullable lease_expires_at_ms, nullable last_reason_code, created_at_ms, updated_at_ms. Multiple jobs may originate from one event. No global UNIQUE(kind, subject) rule should discard independent deliveries. The coordinator must use lease-token and expiry checks to prevent stale owners from committing. A job result does not, by itself, prove acquisition or episode coverage.

**Incremental compatibility:** PR #94's `webhook_events` includes historical work-state fields and `save_identity` operates on them. This follow-up adds dedicated `jobs` storage; removing old event-state coupling and implementing real workers is distinct later work. Do not mistake the existence of a jobs table for a functioning coordinator.

**Scope:** SQLite schema, basic persistence helpers, documentation, isolated tests in `src/nextgen/tests/`. No intake HTTP service, no daemon, no acquisition, no migration from legacy, no production deployment. Leave automatic paid CI disabled; tests remain tracked, with offline comprehensive testing planned later per user decision. Do not claim unrun tests have passed. No merge/deployment without fresh authorization.

## Versioned SQLite SQL files — PR #95

The future **NextGen-only** migration component will read ordered scripts from `src/nextgen/storage/sql/`:

- `001_foundation.sql` creates exactly the initial six-table NextGen foundation and sets `PRAGMA user_version=1`. Use this only on an empty NextGen database.
- `002_independent_jobs.sql` adds the independent `jobs` and append-only `job_history` tables and their indexes and sets `PRAGMA user_version=2`. Apply this to a version-1 NextGen database. It does not recreate the six existing tables or alter their rows.
- On a fresh database, run 001 then 002. On an existing verified v1 database, run only 002. At v2, do not reapply either script.

The migration component is **not implemented** in this PR. When built, it must check `PRAGMA user_version`, reject missing/unknown/unexpected versions, apply each SQL script atomically (including its version bump), and verify integrity. A failed migration must roll back without claiming the new version. Never run these scripts against legacy production databases. The Python `initialize()` helper creates v2 on a genuinely empty database and rejects implicit upgrades of v1 rather than silently stamping a later version. Existing `webhook_events` work-state columns remain until a separate compatibility change.

## NextGen processing components

Explicit static components, each with narrow responsibility:
1. **Webhook intake:** accept each authenticated, reasonably bounded delivery, retain the supplied release name as-is and write the delivery durably. No anime/episode/GUID/name-based deduplication here. Deliveries are observations, not series.
2. **Identity and cache:** resolve identified AniDB anime + exact AniDB episode(s), real title and TVDB series link. Reuse previously established cache evidence when applicable, while checking it applies to each input. No provider scoring/voting system and no assumption that altered title means new anime. The **identity gate** validates before marking done.
3. **Canonical episode claim:** once an exact episode identity exists, atomically determine if work for that episode has already been claimed/handled, preventing duplicate acquisition under parallel submissions. Preserve every source delivery and trace history.
4. **Acquisition:** own torrent operations, torrent identity/ownership, configured size limits, and Japanese + English audio checks. Do not infer identity from an acquisition job.
5. **Staging/Jellyfin:** own staging files and NFO output; require necessary TVDB placement for the particular operation and validate path/filesystem ownership at the moment of use.
6. **Human review and Sonarr export:** explicit Keep or Reject; exact export is never authorized merely by staging or by an identified series. Preserve existing hard-won mapping and safe import semantics, without linking runtime legacy code.

The coordinator owns bounded durable scheduling, not business-logic decisions. Logging/history uses stable per-delivery Postfix-style `AD-N` trace IDs and independent job IDs, *outside* AnimeSeries. Store structured durable history with safe reason codes, retries, cache activity and component boundaries; protect credentials and other sensitive data in logs.

## NextGen tests: fresh, local batches, no automatic GitHub checks

The clean-slate code uses its **own** tests in `src/nextgen/tests/`. The legacy tests in `src/legacy/` are preserved for history and regression behavior, but MUST NOT gate or be imported by NextGen implementation. The legacy tests need not inherently fail; they simply validate a different runtime.

The automatic GitHub Actions **Python test workflow has been removed** on this draft PR branch. Do not automatically run legacy or NextGen tests on pushes or pull requests. Keep the separate manually invoked archive publishing workflow unchanged. If branch protection requires a deleted check, resolve that repository rule explicitly before merging; do not silently bypass it.

Use `python -m src.nextgen.tests.run_batches --match schema` for focused schema work, or `python -m src.nextgen.tests.run_batches` for all NextGen tests, executed in separate groups of up to five test files. Use `--batch-size N`, `--match <filename-part>`, and `--list` as needed. This needs Python 3.12+ and runs **locally/on demand**, never against live services. See `src/nextgen/tests/README.md`. Each new NextGen component gets its own isolated offline tests and sample data in the existing `fixtures/` folder. Current project policy defers test execution: commit relevant tests and document them as unrun. The commands above are for later explicit authorization.

## Next PR: delivery and worker reliability (TCP-like, application-level)

**Primary goal:** a webhook receipt that got HTTP success must not disappear or be silently unprocessable after a crash. TCP is an analogy for acknowledge/retry/recovery; do not promise literally failure-free or exactly-once execution.

Scope:
- Fresh standalone NextGen webhook handler, authenticated/validated/size-bounded, plus **fresh** SQLite durable inbox. Acknowledge successful submissions only **after** durable commit.
- Commit both the delivery record and its pending identity work marker atomically. This may be one inbox row with `PENDING` status; do not assume a separate executable job row per webhook is required.
- Bounded processing, leases or recoverable claims, retry/backoff on temporary failure, explicit permanent-error/manual-review state, graceful backpressure/retryable HTTP responses under overload.
- Every accepted delivery remains independently traceable; no content-based deduplication at intake. Identity caching and *post-completion* episode claims are separate later work. Nothing in the series schema tracks retries, attempts or delivery receipt.
- Offline fault-injection and concurrency tests: 10,000 requests with duplicate or changed release names, process death between commit and acknowledgment, crash during work, SQLite failure, restart recovery, provider unavailable, poison payload, duplicate acquisition claim protection (when built), log correlation, and bounded resource usage.
- No production changes, no real provider integrations, no live acquisition, no Jellyfin/Shoko/Sonarr side effects and no migration of legacy data.

Failure semantics: **accepted does not mean identified; identified does not mean acquired.** A validation failure fails *that identification attempt* cleanly. System-wide crashlessness is a design target, not an absolute guarantee; persistence, recovery and visibility are testable service invariants.

## Regression expectations and PR boundaries

Preserve domain behaviors as test cases, not code bridges: AniDB versus TVDB sequel/cour disagreement, Re:ZERO's verified mapping and exact episode references, season zero/specials, multi-episode releases, ambiguous or duplicate mapping, missing provider data, safe file ownership, dual audio, and explicit human approval.

- **PR #89:** closed without merge, superseded.
- **PR #90:** independent optional backfill design, **not** automatic backfill for NextGen.
- **PR #91:** draft exploratory traces/docs from legacy; outdated migration suggestions are superseded. Do not merge a stale handoff.
- **PR #92:** merged into `NextGen`, offline-only AnimeSeries v1 schema and RFC identity-completion tests. Superseded by a proposed minimal V2 schema revision; no NextGen deployment or background worker included.

The separate SQLite/webhook-design effort implements **durable intake/reliability infrastructure**, not the identity provider algorithm or media integrations. V2 schema work stays in its own draft feature PR.
