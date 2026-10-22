# Component boundaries and job infrastructure (foundation)

## Decision

Keep the existing verified AniDB/TVDB identity and season-mapping logic, evaluation eligibility, acquisition authorization, Japanese/English audio and size checks, Jellyfin NFO generation, explicit Keep, and Sonarr export behavior **unchanged**. Do not relocate TVDB reconciliation to export in this PR: current staging and NFO validation require a verified TVDB ID.

## Existing durable architecture

- `notifications` is the immutable reference point for an incoming release and remains Series History, keyed idempotently by source and GUID.
- `daemon_jobs` (already on `develop`) owns leases, retries, and executable work; jobs are independent.
- `unified_identity_checks` retains provider evidence and the legacy identity monitor's own retry timing. **Replacing this monitor is not included here.**
- `episode_dispatch` and verified identity/provenance records enforce the existing acquisition and staging workflow.
- `anime_diagnostics.event` is the structured, redacted operational logger; journald remains the real-time diagnostics stream.

## Component contract for future extractions

A component owns **one responsibility**, is invoked explicitly by its caller, accepts validated inputs, returns a documented typed result, and must not silently reinterpret upstream verification. No dynamic registration, provider voting, generic hooks, or runtime plugin discovery.

Suggested boundaries, without committing to new runtime interfaces in this PR:
1. Notification intake: persist/deduplicate a received release, never trust the release name as episode proof.
2. Identity: existing single authority over verified AniDB/TVDB relationship and exact season/episode mapping.
3. Acquisition: only existing approval/safety gates may authorize a download.
4. Staging: dual-audio/size/media evidence, existing NFO metadata and filesystem rules.
5. Keep/Sonarr: explicit choice, verified import identity, and protective cleanup rules.

The above is an extraction guide, **not** authorization for a simultaneous rewrite. Extract each existing component under regression tests in a later, narrowly scoped PR.

## Reusable tracing

`anime_trace_history.py` is extracted from the superseded PR #89; it provides a bounded, sanitized append-only SQLite event API. `AD-<notification ID>` follows notification-related jobs; standalone jobs use `AJ-<job ID>`. The existing daemon emits job start/finish into both SQLite history and the event logger. These are observability records, not workflow-control flags. Failure to append a trace event must not change whether a job runs or finishes.

For now the low-level history API is intentionally independent of the dashboard. A future dashboard change should present timelines without inventing statuses from log messages. No hook-execution events, identity worker replacement, backfill, startup migration, or new database are added here.

## Safety and rollout

- Do not change or backfill `notifications`, migrate production state, or touch media/torrents.
- Do not merge or deploy on CI alone. Test worker lease recovery and tracing failure isolation separately.
- Keep PR #89 unmerged as a historical reference until the replacement is reviewed.
