# NextGen Prowlarr discovery — first implementation batch

PR #90 was a design-only placeholder, not the source of an enabled feature.
This batch ports the small, reusable pieces from
`src/legacy/anime_prowlarr_search.py` and
`src/legacy/anime_release_matching.py` into
`src/nextgen/acquisition/prowlarr.py` without importing the legacy worker,
database, webhook or approval pipeline.

## Implemented

- A read-only, bounded Prowlarr `/api/v1/search` client, with a caller-supplied
  URL, private API key, timeout and injectable transport.
- No redirects, query-URL credentials, unbounded JSON responses, torrent
  download URLs, or implicit torrent submission.
- Conservative exact-verified-alias candidate filtering for explicit
  season/episode hints, 40-character BTIH magnets and seed-count ties.
- Candidates must fall within an **explicit caller-provided** set of wanted
  episode positions. Season-qualified aliases require an explicit season in
  the release title; multi-episode ranges are excluded.
- Offline fake-transport and pure matching test cases (auth, malformed
  responses, season scope, ambiguity and frozen selection windows).

The adapter itself **does not verify AniDB/TVDB mappings**. Even a selected
Prowlarr result is only a search hint: NextGen must independently verify
identity and coverage, reserve episodes, verify exact torrent metadata and
media, and enforce size/audio/ownership rules before any download.

## Window policy (already implemented in NextGen)

The source of truth remains `src/nextgen/trial_policy.py:Window`.
A season 1 episode 10 trigger with backfill=6 and following=1 creates
eligibility for E01–E06 and E10. Following=2 means E10–E11; following=6
means E10–E15. Overlaps are deduplicated. These are **episode positions**,
not permission to create unknown provider identities.

For the requested new behavior, active backfill should search only missing
verified positions among E01–E06, once per frozen series/season/trigger scope.
Following positions should ordinarily be admitted **when releases arrive**,
not searched ahead or downloaded early.

## Not yet implemented (separate batches)

1. Wire Prowlarr URL/API-key to the versioned NextGen settings/secrets and
   authenticated management API; preserve explicit migration and revisions.
2. Register a separately named gap-discovery worker job after completed
   independent identity/episode verification. Acquire verified known aliases
   and exact TVDB/AniDB season scope from NextGen storage, not webhook claims.
3. Search only missing eligible backfill episodes. Check staged files,
   active reservations and in-flight work transactionally; deduplicate
   requests/retries; store bounded, readable candidate diagnostics.
4. Handoff candidates through NextGen's ordinary trusted intake,
   verification, reservation and acquisition path; **never** call legacy
   `receive` or `enqueue` from NextGen. An indexer result is not an
   automatic download authorization.
5. Add offline fake-Prowlarr integration and worker crash/retry tests before
   enabling live automatic searches.

There are intentionally no changes to the installed worker composition,
database, schema, credentials, UI, active releases, or torrent operations.
No CI was triggered by a PR because this work is on a separate branch only.
