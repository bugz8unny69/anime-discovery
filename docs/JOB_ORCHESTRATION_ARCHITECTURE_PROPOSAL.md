# Job orchestration architecture — design and work items

Status: **proposal only; no runtime behavior changed**. Review before implementation. Target: `develop`.

## Problem and current state
Autobrr webhooks are captured as `notifications`, while the service **already has** a general `daemon_jobs` queue with `kind`, `subject_key`, payload, lifecycle state, leases and retries. Notifications are durable intake/evidence records, **not interchangeable with worker jobs**. `anime_webhook_processing.receive()` creates a notification; the unified identity monitor processes identity and may call `approve()` to enqueue `claimed_acquisition`. Another path `receive(...,gap_search_enabled=True)` can enqueue `series_gap_search`, which is executed by the registered worker/Prowlarr handler. The unified identity path does not schedule that backfill and treats an intentional episode-range exclusion thrown by `approve()` as `LOOKUP_ValueError`, repeatedly retrying and eventually requiring review.

Evidence: October 21 logs for notification #30 show `VERIFIED_SEASON_REMEMBERED` (TVDB 475631, AniDB 19954, S01), `OUTSIDE_TRIAL_WINDOW` for E10 (E01–E06), `anime_webhook_processing.py:57` ValueError, and misclassified `LOOKUP_RETRY` then `NEEDS_REVIEW`. Notifications #28/#31/#32 demonstrate similar errors. No claim is made that production configuration, job DB, or Prowlarr availability has been independently verified.

## Confirmed design constraint: preserve notification history
- **Do not remove, rename, replace, or repurpose the existing `notifications` table.** It is part of the Series History model and must retain its records and links.
- Job orchestration is additive: worker jobs may reference their initiating job and a persisted notification and series-history association. Series History must continue to display historical notifications independently of the Jobs activity view.
- Migration and tests must prove existing Series History behavior and historic notification IDs remain intact. No data loss or breaking history queries.

## Proposed architecture (decision requested)
- **Webhook = event/inbox record**, not automatically the entire job. Retain an immutable or append-only inbound notification/event record for deduplication, source provenance, replay/audit and original release evidence.
- **Job = scheduled executable work.** Webhook intake should durably enqueue an identity-resolution job (or equivalent explicit existing worker task), rather than using notification state as an implicit work queue. Jobs can enqueue child jobs: identity -> either verified acquisition or season catch-up search -> per-episode acquisition -> validation/staging tasks where useful. Do not blindly split every synchronous step into its own job.
- Keep one authoritative job scheduler, reusing `daemon_jobs` leases, cancellation and recovery. Do **not** rename the `notifications` table to `jobs` or introduce a competing queue. Assess if the identity monitor should become a job handler rather than layering a new scheduler on top.
- Use minimal optional correlation: `triggered_by_job_id` (the first job to schedule this work) and `notification_id` (Series History). Do not introduce a root-job tree, completion dependencies or automatic status propagation. Preserve idempotency keys so duplicate triggers reuse the same job.
- Job state, business outcome and user-facing wording are distinct. An identified-but-excluded triggering episode is not an identity lookup error and should not be retried as one. Each job completes independently after its own work (including durable scheduling of the next job), without waiting for downstream jobs.
- Atomic, idempotent **event persistence + first job enqueue**, and atomic or transactional **job -> next job enqueue**; recover safely from crashes between operations. Repeated webhook, retry, restart and concurrent workers must not duplicate acquisition.
- Design bounded fan-out, concurrency, rate limits, per-episode ownership arbitration, Prowlarr deferral, immutable evidence, cancellation semantics and sensitive-data-safe activity history. Preserve manual Keep separate from staging and Sonarr downstream.

## Work items — plan only
1. Inventory all workflows and tables: `notifications`, identity polling, `daemon_jobs`, `episode_dispatch`, `series_gap_search`, Prowlarr settings/runtime, batch jobs, admin actions, dashboard Jobs/Activity, cancellation/recovery, and potential future heavy settings-related actions. Document current edges and state owners.
2. Write an ADR and workflow/state diagram: job versus incoming event versus notification; job kinds, handoff links, source correlation, lifecycle and outcome taxonomy; specify whether existing `notifications` persists as inbound event storage. Decide which operations genuinely need asynchronous jobs.
3. Design **additive SQLite migrations**, indexes, historical lineage backfill only where provable, read-only UI compatibility, mixed-version/rollback policy, and duplicate-safe crash recovery. No destructive rename.
4. Provide a staged plan: first add durable job lineage and activity; then enqueue explicit identity jobs via webhook; then migrate identity processing incrementally, with no worker duplication; preserve existing queue behavior during transition.
5. Define job status & dashboard UX: show webhook receipt linked to identity job and child tasks, timestamps, optional triggering-job links, independent child outcomes, clear reasons, refresh persistence; avoid presenting every raw notification as a worker job.
6. Regression case from incident: verified S01E10 outside configured E01–E06 range should mark E10 **skipped** and enqueue one bounded Prowlarr season catch-up search; candidates E01–E06 (when available and verified) reuse existing acquisition, JP+EN ffprobe, size/ownership checks, and staging; E10 must not be acquired; no `LOOKUP_ValueError` or retry exhaustion.
7. Validate existing `anime_shared_discovery.schedule()/search_once()`, `anime_prowlarr_search`, and worker `series_gap_search`; require a verified provider-backed search alias, skip staged/in-flight episodes, address idempotency across distinct later-episode triggers, and report missing/ambiguous results without implying all six downloads succeeded.
8. Add offline tests for duplicate webhook, duplicate job-to-job handoff, concurrent workers, crash/restart at enqueue boundary, retries, disabled/unavailable Prowlarr, partial search results, ownership/recovery, and a downstream job failing while the triggering identity job remains completed.
9. Separate future jobification candidates (long-running admin/settings operations) into follow-up design. Don't introduce a blanket rule that saving basic settings requires asynchronous execution.

## Non-goals and safety
- No runtime code, schema migration or service changes in this PR.
- No live VM, SQLite, qBittorrent, NAS, torrents or media actions.
- Do not merge or deploy without explicit approval.
- Do not remove identity checks, allow unverified acquisition, bypass trial-size budgets, promote alternate torrents before proven cleanup, auto-stage invalid files, or auto-Keep.
- User-facing language should avoid unexplained “verified trial window” and generic `LOOKUP_ValueError`; propose concrete “Episode 10 skipped; searching for missing episodes 1–6” when backed by persisted facts. Internal names can migrate separately.
- Backfill must not claim success if no candidates were found, downloaded, validated and staged.

## Open design decisions
- How should immutable notification and Series History references be displayed alongside correlated root/child jobs? **The `notifications` table and its Series History function are non-negotiable and remain intact.**
- When multiple jobs request the same search, keep the first `triggered_by_job_id` for audit while deduplicating the work; do we need additional audit events for later triggers?
- How should the UI communicate downstream status without falsely changing an already completed job's state?
- What does a future heavy settings action need: transaction, immediate effect, deferred apply, audit, retry, or a separate approval gate?

Implementation requires follow-up approval and focused PR(s).