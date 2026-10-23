# Trial episode windows

The policy selects trial intents. It does not download files, search providers,
claim acquisition resources, verify file contents or permanently Keep an anime.

## Settings and exact counting

| Setting | Default | Meaning |
| --- | --- | --- |
| trial.backfill_count | 6 | Select the first X episode positions of the verified official TVDB season |
| trial.following_count | 1 | Select X positions starting with the triggering episode, including that episode |

Both are integers 0–1000. Zero disables that particular window; no separate
boolean flags or combined maximum are needed. A received episode is included
only if one of the windows selects it. Following 1 includes just the trigger;
following 2 includes the trigger and the next episode. Counts represent two
independent allowances and overlapping positions count once.

| Trigger | Backfill | Following | Requested positions |
| --- | --- | --- | --- |
| 10 | 6 | 1 | 1–6 and 10 (7 distinct episodes) |
| 10 | 0 | 2 | 10–11 (2 episodes) |
| 10 | 0 | 6 | 10–15 (6 episodes) |
| 3 | 6 | 2 | 1–6 (6 episodes, with overlap deduplicated) |
| 10 | 6 | 0 | 1–6; episode 10 is outside the window |
| 10 | 0 | 0 | Invalid configuration; at least one count must be positive |

## Stable plan and season boundary

The first successfully committed EVALUATE_TRIAL completion creates the plan for
(anidb_id, tvdb_series_id, official TVDB season/order). It fixes the triggering
episode, both counts, source verification and configuration revision. Concurrent
jobs can run normally; one short SQLite transaction wins plan creation, and the
other evaluations reuse it. The winner is the first committed evaluation, which
may differ from delivery timestamp order when verification jobs finish out of order.

For an anchor of 10 with following=2, episode 11 is selected but cannot extend
the window to 12. Repeated deliveries, retries and later events never move the
anchor. Different verified seasons have separate plans. Multiple AniDB entries
sharing a TVDB series remain separate identity scopes; they are not merged.

Settings changes apply to new plans. Existing plans retain their recorded counts,
anchor and revision; changing settings is not an implicit replan/reset. Explicit
replanning, lifecycle/retention and management controls are future work. Both
counts zero is rejected during configuration conversion, validation and update,
and by the standalone window contract. At least one count must be positive.
A rejected update leaves the saved settings and existing plans unchanged.

All requested positions stay within the recorded season scope. Numeric intent
does not assert that a future episode already exists, has aired or belongs to
the same AniDB entry. In split/part mappings, later backfill/acquisition logic
must independently resolve episode ownership and review out-of-scope targets;
a plan cannot authorize another AniDB entry or guess identifiers. No future
AniDB/TVDB episode IDs are manufactured from these ranges.

## Worker and durable decisions

The composed worker now runs IDENTIFY_ANIME → VERIFY_RELEASE → EVALUATE_TRIAL →
RESERVE_EPISODE.
The release handler supplies an explicit verification-job reference; the new
handler loads its committed declared-episode evidence for the same incoming
event and checks source/canonical identity. created_by_job_id remains provenance,
not a parent/child workflow or dependency engine.

The worker rechecks evidence and records the immutable plan plus per-job decision
inside its lease-fenced completion transaction. Plan creation, decision,
TRIAL_EVALUATED audit, handler ending and job completion commit together. A failed
or stale completion cannot leave a plan behind. Evaluations store selected and
TRIAL_SELECTED or TRIAL_OUTSIDE_WINDOW. TRIAL_DISABLED remains registered only
for historical compatibility; new evaluations never emit it. Every code resolves
static readable messages/actions and translation keys. The history marker is durable regardless of logging verbosity. Its application-log
receipt is emitted only after commit and respects the configured logging level.

A DONE evaluation means the policy decision is recorded. It does not mean the
episode was acquired or staged. The next job reserves only a selected verified episode; no external acquisition
successor is installed. Selected
backfill/following positions remain intents for later exact-resource/inventory,
provider search, ownership and trial publishing work. The future dashboard can
expose the settings through existing field metadata; no dashboard or management
HTTP endpoint is implemented by this change.

## Versioning and review status

Configuration v4→v5 explicitly adds the two defaults and advances revision once.
Historical v0→v4 converter outputs keep their original shapes. SQLite v10→v11
adds trial_plans and trial_evaluations with matching fresh schema, helpers,
version guards and offline cases; numbered migrations 001–010 stay unchanged.
AnimeSeries stays v2. The prerequisite provider, release and selection PRs #110–#112 are merged.

Offline tests cover corrected counting, zero/overlap/bounds, frozen plans,
configuration changes, concurrency, source/lease safety, rollback and migration
preservation/fresh equivalence. Tests remain **unexecuted** under project policy.
Only source review, syntax-only AST and diff/DDL source checks were performed.
No tests/CI, application imports/execution, SQL, live providers, download/media
operations, permanent Keep, production changes or deployment occurred.

## Episode reservation handoff

The composed worker now queues RESERVE_EPISODE after each committed evaluation.
The gate reads the durable decision: outside-window work records a readable
skip without reserving; selected verified received episodes can obtain an exact
slot. Backfill/future positions still need provider-backed release evidence.
See jobs/RESERVE_EPISODE.md. This refines the earlier no-successor description;
there is still no external acquisition route. SQLite is now v12.
