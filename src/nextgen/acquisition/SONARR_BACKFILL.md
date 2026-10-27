# Batch 2 — opt-in Sonarr backfill discovery

Batch 1 supplies a read-only Sonarr interactive release-discovery client. Batch 2 schedules
bounded search observations for the **first X episodes** of a **frozen**
`trial_plans` window. Neither batch submits torrents or authorizes acquisition.

## Activation

Explicitly upgrade the NextGen SQLite database from v41 to v42 under the
existing maintenance/migration flow. Neither startup nor this handler upgrades
the database implicitly. Do **not** operate an old worker against a v42
database; restart with compatible worker code before reopening admission.

The default provider worker retains prior behavior. To opt into backfill
observation, a trusted caller supplies `sonarr_backfill=True` to
`build_identity_worker(...)`. The existing Sonarr URL, API key and timeout
are used. Interactive release requests allow 180 seconds while other Sonarr API
requests retain the configured timeout. The feature introduces no Prowlarr account.

**This branch is not deployed and the v42 migration has not been applied.
Automated offline validation is tracked by draft PR #159.**


## Local candidate selection (discovery only)

Sonarr quality profiles are **not** imported. Three managed settings control
Anime Discovery's candidate preference for subsequent searches:

| Setting | Default | Behavior |
| --- | --- | --- |
| `sonarr.discovery_max_resolution` | `1080` | Upper bound: 720p remains eligible when set to 1080p; supported values 720, 1080, 2160 |
| `sonarr.discovery_min_seeders` | `5` | Missing counts and counts below this value are ineligible |
| `sonarr.discovery_rank_by` | `resolution` | `resolution` first then seeders, or `seeders` first then resolution |

Original Sonarr results remain observable, but locally acceptable single-episode
torrent candidates rank first. Sonarr-approved/rejected and custom-format
decisions are retained for diagnostics and do not authorize or prohibit local
discovery. Backfill `exact` counts locally acceptable candidates, while
`approved` remains a separate Sonarr verdict count.

Sonarr v4/Prowlarr sometimes puts a complete `magnet:?` link in `guid` while
leaving `magnetUrl` empty. Such GUIDs are accepted **only after validating
their BitTorrent v1 hash** and rejecting a conflict with `infoHash` or the
other supplied magnet. HTTP GUIDs, `downloadUrl` and indexer passkeys are
**not followed, rewritten or submitted** here. Magnets and hashes are
transient response data, not stored in backfill receipts or logs.

All sources still require exact independently anchored Sonarr episode mapping;
unknown-series results, season packs and cross-season mismatches cannot become
automatic single-episode handoffs. No direct torrent submission is wired to
this read-only observation job; actual acquisition remains a separate step.

## Frozen window

On the first successfully committed `EVALUATE_TRIAL`, the worker retains
the original plan anchor and counts, and atomically inserts one discovery
job per trial plan only when `backfill_count > 0` and the opt-in handler
is installed. Further incoming episodes of the same AniDB anime/TVDB season
cannot enqueue a second chain. Discovery is scoped to episodes
`1..backfill_count` — **not** the entire continuation range.

Each `DISCOVER_SONARR_BACKFILL` attempt handles up to **four** positions,
then atomically stores summary receipts and schedules the next page on
successful completion. The existing operation's cancellation and worker
lease/transaction rules apply. Failure to contact Sonarr retries using the
worker's standard failure budget; missing Sonarr series is held for review.
No new DB job payloads contain credentials, magnet URIs, or download URLs.

For E10 with backfill 6 and following 2:
- The first evaluated plan schedules E01–E04, then E05–E06.
- E10 and E11 remain covered **only as matching releases arrive through
  the existing intake flow**; the batch does not proactively search E11.
- When Sonarr already has a file or NextGen has an active reservation,
  the episode is recorded without sending an indexer query.

## Recorded results

`sonarr_backfill_results` (v42) is a new **observation-only** table:

| Column | Meaning |
| --- | --- |
| `plan_id`, `tvdb_episode` | Frozen plan and season position; unique |
| `job_id` | Worker provenance |
| `sonarr_episode_id`, `tvdb_episode_id` | IDs **as reported by Sonarr**, not independent verification |
| `status` | `IN_PROGRESS`, `NOT_LISTED`, `IDENTITY_UNKNOWN`, `IDENTITY_CONFLICT`, `HAS_FILE`, `CANDIDATES` or `NO_RESULTS` |
| `candidates`, `approved`, `exact` | Total results, Sonarr-approved exact matches (diagnostic only), and locally acceptable exact torrent candidates |
| `observed_at_ms` | Recorded wall-clock observation time |

A read-only query to review progress after running an enabled worker:

```sql
SELECT p.anidb_id,p.tvdb_series_id,p.tvdb_season,
       r.tvdb_episode,r.status,r.candidates,r.approved,r.exact
FROM sonarr_backfill_results AS r
JOIN trial_plans AS p USING(plan_id)
ORDER BY r.plan_id,r.tvdb_episode;
```

### Critical identity boundary

The verified incoming anime/season is the scope anchor. Backfilled episode IDs
may come **only from Sonarr's catalog** until a provider-verified per-episode
mapping exists in `recognized_episodes`. The worker cross-checks a recognized
ID when available, marking conflicting identities without searching.

Sonarr catalog IDs and Sonarr's `approved` flag **never prove** an AniDB
episode identity, JP+EN audio, or a correct torrent. The DB records no torrent
hashes or URLs, has no reservation/submit permit, and has no automatic
re-queue or download handoff. Additional AniDB/TVDB verification and actual
download ownership are distinct future batches.

The Sonarr GET request contacts indexers and can update episode last-search
timestamps. Search-only opt-in is intentional, so installing the branch or
running a normal worker does not automatically create these requests.

## Offline live-response validation

A previously captured Sonarr `GET /api/v3/release?episodeId=...` JSON array
can be inspected **without further indexer queries or downloads**. The following
invocation is for the verified Solo Leveling S01E01 example; substitute IDs
that match the response file:

```bash
python3 -m src.nextgen.acquisition.validate_sonarr_json \
  /tmp/sonarr-releases.json \
  --sonarr-series 126 --sonarr-episode 2504 \
  --tvdb-series 389597 --tvdb-episode 7979142 \
  --season 1 --number 1
```

The report prints scope distributions, count of validated magnet sources,
number of locally eligible candidates, and the top ten candidates' resolution,
seeders, indexer and Sonarr verdict. It deliberately does **not** print raw
magnets, hashes, GUIDs or download URLs. It does not inspect tracker content,
prove AniDB episode ownership, fetch torrent metadata, or submit a torrent.
Saved Sonarr JSON may contain confidential tracker links: store it privately.

## Acquisition handoff admission (next batch boundary)

`sonarr_handoff.admit_candidate(...)` is a **pure, side-effect-free**
bridge between a ranked Sonarr result and an existing acquisition source.
It requires:

- A candidate present in the specific Sonarr `SearchResult`, with exact
  episode scope and a validated magnet/info-hash identity.
- Locally accepted resolution and seeder count. Sonarr's approval remains
  diagnostic only.
- `AcquisitionInput` obtained through the existing
  `load_acquisition_input` admission path, carrying an active, provider-verified
  episode reservation and incoming release hash. Sonarr cannot invent this
  missing provenance.
- The candidate hash matching the immutable incoming release hash, plus
  independently fetched torrent metainfo parsed against that hash, matching
  the reserved episode filename and size constraints.

The output is a transient `AdmittedCandidate`; it is **not** a submission
permit or persisted torrent job. The original `PREPARE_ACQUISITION` and
`SUBMIT_TORRENT` worker steps retain their fenced transactions, manifest
recheck and one-shot stopped-download authorization. No alternate qBittorrent
submission route or arbitrary Prowlarr URL-fetching path is created.

This bridge intentionally does **not** yet enable acquisition of a Sonarr-found
torrent whose hash differs from the incoming torrent hash. That requires a
separate, independently verified and durably recorded selection/provenance
operation with cancellation and duplicate handling. Do not substitute a
Sonarr-guid magnet for that operation.

## Durable source choice foundation (SQLite v43)

Version 43 fixes the old `exact <= approved` observation constraint:
NextGen's locally eligible count and Sonarr's approved count are independent.
For example, `approved=0, exact=16, candidates=308` is valid.

A small `sonarr_episode_selections` table records exactly one normalized
torrent info hash for a recognized episode within a frozen Intake plan.
`storage.sonarr_selection.select` requires the call to run inside an
already admitted SQLite write transaction. It uses existing
`recognized_episodes`, `trial_plans`, and both active reservation
namespaces to reject unknown identities, out-of-window episodes,
competing reservations, hashes reused for multiple episodes, and
conflicting selections. Repeating the identical choice is idempotent.

This receipt does **not** replace the incoming event's torrent hash,
invent an AniDB verification, reserve an episode, enqueue any worker job,
or authorize a torrent submission. It also does not yet fetch torrent
metainfo for independently discovered hashes. A future small worker
integration must perform source selection in a fenced transaction and
hand verified metainfo into the existing preparation/submission machinery.
Until then, the selection function is an unwired foundation.

Do not deploy the v43 schema without the compatible worker version and
an explicit maintenance migration. The v42 SQL file is unchanged; v43
provides an additive upgrade and fixes the observational constraint.

## Remaining work

Offline tests in `tests/test_sonarr_backfill.py` and
`tests/test_sonarr_discovery.py` cover paginated work, deduplication,
explicit opt-in, retry, version upgrade, and safe positional queries.
Their results must be checked in PR #159 before merge.

Before activating: run these tests, validate migration and code against the
running Sonarr v4 configuration, check recognized season mapping and indexer
request rate, and ensure that missing Sonarr series are registered through
an explicit, separately reconciled operation. Automated candidate acquisition,
follow-up proactive search, and the dashboard remain out of scope.
