# NextGen SQLite schema and change policy

## Mandatory rule: application changes and SQL schema changes go together

**Any PR that adds, removes, renames, or changes a SQLite table, column, index, foreign key, constraint, trigger, or persisted data shape MUST update the NextGen schema in that same PR.** Do not introduce a code-only SQL change that works solely because somebody manually patched a database. Likewise, do not ship a migration that leaves the Python persistence layer or its schema snapshot inconsistent.

For every change, contributors must:

1. Add the next numbered SQL file under `src/nextgen/storage/sql/` for existing database upgrades, with a documented expected starting `PRAGMA user_version`, atomic upgrade semantics, and the new version. **Never edit an already published numbered migration** to change its meaning.
2. Update the latest fresh-database `SCHEMA` in `src/nextgen/storage/sqlite.py`, including dependent foreign keys, constraints, indexes and references, and update the fresh-database `user_version`.
3. Update every matching SQL query, insert/update helper, and model-to-storage mapping used by the component. Do not put business logic or operational/job fields into the `AnimeSeries` domain model merely to avoid a DB change.
4. Add or update offline tests in `src/nextgen/tests/` for both a **fresh database** and the **sequential upgrade path**, including representative existing rows, referential integrity, and rollback/failure behavior. Commit these tests even when test execution is deferred.
5. Update **this document** when table meaning, schema version, relationships, or migration instructions change. Document any new columns and whether they can be NULL, their defaults, and their validation rules.
6. In the PR description, list the schema version transition, files changed, compatibility considerations, and whether tests have been run. Never describe unrun tests as passing.

This applies to **all** future components, including intake, coordinator, supervisor, identity, dashboard and `m` admin commands. Any program needing a new table or new stored field must accompany that requirement with a versioned schema change; no silent ad-hoc `CREATE TABLE` or `ALTER TABLE` inside runtime components.

## Current NextGen SQLite state (PR #100 implementation)

Latest fresh SQLite version: **6**. The version stored in `PRAGMA user_version` is the **database schema version**, separate from the `AnimeSeries` Python domain `schema_version` (currently 2 in the checked-in SQLite identity-results constraint).

| Version | SQL file | Purpose |
| --- | --- | --- |
| 1 | `001_foundation.sql` | Historical foundation: accepted events (`webhook_events` at that version), event history, identified anime and episodes, identity results and episode links |
| 2 | `002_independent_jobs.sql` | Independent `jobs` and `job_history`; `created_by_job_id` is **optional provenance**, not a parent/child dependency relationship |
| 3 | `003_incoming_events.sql` | Rename `webhook_events` to `incoming_events`, preserving rows and updating SQLite foreign-key references |
| 4 | `004_diagnostic_components.sql` | Add nullable emitting component to both history tables, retaining historical rows |
| 5 | `005_job_statuses.sql` | Expand lifecycle states and add typed current/historical activity |
| 6 | `006_api_diagnostics.sql` | Permit the separate api emitter in both history tables |

**Current tables:** `incoming_events`, `event_history`, `identified_anime`, `identified_episodes`, `identity_results`, `result_episode_links`, `jobs`, `job_history`.

- `incoming_events`: durable inbound delivery record. An incoming event is not a notification and need not originate from a webhook. Do not deduplicate accepted deliveries by GUID, release title or payload.
- `event_history`: event-specific timeline and reasons.
- `identified_anime` / `identified_episodes`: verified identities and exact AniDB episode ownership; multiple AniDB anime may share a TVDB **series** ID.
- `identity_results` / `result_episode_links`: validated, versioned identity snapshots and event-specific episode associations. The domain model's optional episode coverage is distinct from operational state.
- `jobs`: independent queued work with optional original `event_id` and `created_by_job_id` provenance.
- `job_history`: durable operational job timeline, independent of journald verbosity.

Current fresh schema definition: `src/nextgen/storage/sqlite.py` (`SCHEMA`), alongside these incrementally versioned historical SQL scripts. They **must remain logically equivalent after the full upgrade sequence**, even though their historical names can differ.

## Migration and deployment boundaries

- Never apply these SQL scripts against the legacy production database. NextGen uses separate database state.
- `initialize(db)` currently atomically initializes an empty NextGen database to v6 or accepts an existing v6 database; it **does not implement a migration runner**. Versioned upgrades for existing v1/v2/v3/v4/v5 files now use the explicit library described in [MIGRATIONS.md](MIGRATIONS.md); initialize() still never upgrades.
- The runner must inspect `PRAGMA user_version`, apply exactly the missing migrations in order, reject unknown/downgrade paths, and back up or otherwise protect state before a live upgrade. It must validate foreign keys and schema state after upgrade.
- A script's comment or `IF NOT EXISTS` is **not** a substitute for checking starting version. A migration must fail safely if applied to an unexpected version.
- SQLite changes that rebuild tables must preserve validated data, indexes, foreign keys, and history; account for transaction safety and SQLite rename/alter semantics.
- Keep SQL transactions short and preserve durable event/job writes and history. Do not infer that a schema change implements coordinator runtime behavior.

## Test preparation policy for the current development phase

**Code and offline tests are committed, but CI and offline tests are intentionally not executed right now**, per the project development decision. Test execution and any discovered failures are deferred and must be reported honestly. Keep test fixtures and explicit fresh-schema + migration-path regression cases ready for later local execution. No production deployment is implied by merging.

## PR checklist for any SQLite-affecting change

- [ ] New numbered, immutable-history-preserving SQL migration committed (unless no persistence shape changes)
- [ ] `src/nextgen/storage/sqlite.py` fresh schema and `user_version` updated
- [ ] Runtime SQL/queries and all dependent table/column references updated
- [ ] Fresh-install and sequential-migration tests added/updated
- [ ] Schema reference and migration notes here updated
- [ ] Test execution status accurately documented (currently **not run**)
- [ ] No legacy DB, production service, automatic CI or deployment touched

## Reference PRs

- [#93](https://github.com/bugz8unny69/anime-discovery/pull/93) — Python `AnimeSeries` v2 domain schema; **not** a database migration.
- [#94](https://github.com/bugz8unny69/anime-discovery/pull/94) — SQLite schema foundation v1.
- [#95](https://github.com/bugz8unny69/anime-discovery/pull/95) — SQLite jobs foundation v2.
- [#98](https://github.com/bugz8unny69/anime-discovery/pull/98) — SQLite inbound event naming migration v3.


## v4 diagnostic history fields and writer contract

Both event_history and job_history add component TEXT, nullable with implicit
NULL default, constrained to supervisor/intake/coordinator/identity/acquisition.
NULL denotes unknown origin in historical rows. New history writers require a
valid non-null component; migration does not invent attribution for old rows.
All IDs, raw payloads, identities, provenance, histories and indexes are retained.
No job/event state or AnimeSeries v2 field changes. details_json retains the
bounded shape documented in REASON_CODES.md; registered writers validate it.
Direct historical data is not tightened into a new event/reason SQL enum.

004 checks starting user_version=3 inside BEGIN IMMEDIATE, applies both ALTERs,
sets user_version=4 and commits. On any script error the caller must ROLLBACK;
no production upgrade runner is implemented. A wrong starting version triggers
ROLLBACK at the guard. 001/002/003 remain byte-for-byte unchanged.

The shared history writers require an explicit active transaction, validate
known code/scope/reason combinations, component, timestamps and detail bounds,
and never commit. enqueue_job now requires an active transaction and explicit
component, writes CREATED with attempt=0 and leaves commit to its caller.
The high-level delivery/identity helpers own explicit transactions and log
only after commit; a broken log sink does not invalidate persisted history.

Offline fresh/upgraded schema, existing-data preservation, wrong-version,
foreign-key, rollback and component constraint cases are included but unrun.

## v5 job state and activity support

jobs.state now permits PENDING, RUNNING, RETRY_WAIT, ON_HOLD, NEEDS_REVIEW,
DONE, BLOCKED and CANCELED. The default remains PENDING. ON_HOLD denotes a
condition-based wait, BLOCKED a policy/prerequisite stop, CANCELED an explicit
terminal cancellation. These states must not be claimed automatically. The
future coordinator defines validated transitions and wake-up behavior.

jobs.activity_code TEXT and job_history.activity_code TEXT are nullable with
implicit NULL default, constrained to DOWNLOADING, WAITING_FOR_DOWNLOAD,
WAITING_FOR_SEARCH and SKIPPED_DUPLICATE. SQL constrains current activity pairs:
DOWNLOADING with RUNNING/RETRY_WAIT, either WAITING_* with RETRY_WAIT, and
SKIPPED_DUPLICATE with DONE. NULL is allowed for any state and all old rows.
History activities are snapshots; there is no current-state constraint on an
old history row. The writer captures the job's activity without parsing text.

005 rebuilds jobs at v4→v5, preserving IDs, payloads, attempts, timestamps,
leases, event/provenance FKs and reasons. It recreates the three jobs indexes,
adds the history activity column and checks all FKs before committing v5.
Use only during maintenance with no active transaction and no other DB users.
Because jobs is referenced by itself and job_history, the script disables FK
enforcement before BEGIN. Its caller MUST ROLLBACK on an exception and always
restore PRAGMA foreign_keys=ON in finally, including on failed version/FK guards.
The script restores enforcement on success. Do not use a connection left with
FK enforcement disabled. No production runner is supplied by this change.

Fresh SCHEMA and initialize() now use v5. Published 001/002/003/004 remain
unchanged. No state is inferred from historical reason strings: existing
NextGen jobs keep their exact state and receive NULL activity. This is not a
legacy database import. See JOB_STATUSES.md for the display/legacy mapping.

## v6 separate API diagnostic attribution

The management API is a separate process from the coordinator. Its stable
component identifier is api in logging settings, runtime diagnostics and
both history tables. Using coordinator or supervisor as the API emitter would
misattribute actions and is not a substitute for its own component identity.

006 upgrades v5→v6 by rebuilding event_history and job_history with the expanded
component CHECK vocabulary. It preserves every row, history ID, unknown code,
nullable historical component, typed activity and both history indexes. The
foreign-key constraints remain enabled throughout. An in-transaction version
guard and FK check precede the version bump/commit. On any script error the
caller must ROLLBACK. Published 001-005 remain unchanged.

The current fresh schema and initialize() use v6. This adds attribution only;
no API server, authentication, configuration writer or coordinator is created.
Offline API logger/audit and v6 preservation/rollback/version cases are included
but unexecuted. The latest fresh-versus-sequential metadata case includes 006.


## Explicit migration runner and maintenance admission (no schema change)

`migrations.py` implements preview/apply from existing v1–v6, a validated SQLite
backup, per-version transactions and precommit schema/integrity/FK validation.
`maintenance.py` supplies a durable cooperative process admission barrier;
`admitted_connection()` is available to future runtime operations. No table,
column, index or persisted row shape changes: current schema remains v6, and
001–006 are unchanged. Older paragraphs saying no runner describe the historical
PR boundaries; this section and MIGRATIONS.md supersede that implementation status.

All runtime users must be admitted before accessing SQLite, including an entire
job attempt and its heartbeats/final commit. Apply requires an active exclusive
lease after drainage; it leaves admission closed for compatibility/readiness
checks. Partial chains retain their last committed version; failures/crashes keep
the pending marker, and recovery is explicit. No API/supervisor/coordinator wiring
or production upgrade is supplied or executed here. Offline tests are unrun.
