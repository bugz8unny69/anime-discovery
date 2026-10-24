# Missing-episode candidate discovery — NextGen draft

**Status: implemented as a read-only discovery/inventory stage, not yet an
automatic acquisition bridge. Unmerged, untested, not deployed.**

The trial window remains fixed by the first committed `EVALUATE_TRIAL` for
(AniDB anime, TVDB series, official season). For example, anchor episode 10,
backfill=6 and following=1 selects positions **1–6 and 10**. The existing
received release is already verified, so discovery searches **1–6**, not 10.

## Pipeline and safety boundaries

1. On evaluation completion, the worker atomically enqueues the normal
   `RESERVE_EPISODE` successor **and**, when a Prowlarr URL is configured,
   an independent `DISCOVER_MISSING_EPISODES` job.
2. The discovery job loads the same immutable trial plan with exact AniDB,
   TVDB series, season and anchor, then subtracts already-reserved positions,
   already-verified received episodes, and completed discovery inventory.
   It never invents AniDB/TVDB episode IDs for numeric positions.
3. At most **eight missing positions per job** are searched through the
   configured internal Prowlarr API. The provider query uses a title and
   explicit SxxEyy pattern. The response is capped to 1 MiB / 100 records;
   only single-episode, matching-title, exact-TVDB-season/episode entries with
   a 40-digit hex v1 torrent hash (or equivalent magnet URI) are retained.
   AniDB-only numbered releases and ambiguous batches are not automatically
   mapped or accepted at this stage.
4. The worker lease-fenced completion transaction writes each searched
   position and its bounded candidates to new SQLite v23 tables. Competing
   events/search attempts reuse the existing (plan, position) ticket. A
   continuation search job covers further unsearched positions in the
   original window, eight at a time.
5. Discovery candidates are **not downloaded**, submitted to qBittorrent,
   converted into fabricated Intake verification, or used to reserve episodes.
   A candidate must pass the original AniDB/TVDB release verification, exact
   episode reservation, hash-addressed torrent metadata validation, size
   budget, selected-video verification and staging before any automated
   acquisition can occur. Indexer results alone are not such evidence.

The `FOUND` status means only that candidates were found; it does not mean
the episode exists on disk, has aired, has been downloaded, or can be imported.
`NO_MATCH` means none of the bounded matching candidates were found in this
search pass. New future search triggers and automatic candidate-to-acquisition
admission remain future integration work. Queries are not kept running forever;
a new eligible evaluation can search previously unsearched positions.

## Configuration and inspection

- Explicit config v9→v10 adds `prowlarr.base_url` and
  `prowlarr.timeout_seconds`. Empty base URL disables discovery scheduling.
- Private secrets v5→v6 adds `prowlarr_api_key`. Set it through the authenticated
  dashboard or `PATCH /api/v1/credentials/prowlarr` using
  `expected_revision` and `api_key`. Never pass API keys in query strings.
- Run the **NextGen-only** v22→v23 SQLite migration under exclusive
  maintenance before using the updated worker. No production migration ran
  while authoring this draft.
- With management credentials, `GET /api/v1/missing-episodes` lists recent plan IDs; `GET /api/v1/missing-episodes?plan_id=ID`
  returns selected window positions, RESERVED/NOT_SEARCHED/FOUND/NO_MATCH
  states and at most 100 raw candidate summaries. It is read-only; there is
  no public user-provided search or download endpoint.
- Only Prowlarr's torrent indexers are queried (`indexerIds=-2`). The
  configured server's `/api/v1/search` endpoint accepts a query string and
  `X-Api-Key` request header. The HTTP adapter allows no ambient proxy,
  redirects, arbitrary query path, remote download URL or unbounded body.

## What's genuinely left

**The full missing-episode acquisition flow is not finished.** In particular,
Prowlarr search candidates do not automatically provide the trusted
hash-addressed `.torrent` bytes required by the existing
`PREPARE_ACQUISITION` adapter. Implement a trusted, authenticated metainfo
fetch/reconciliation path, verify the candidate through the existing
AniDB/TVDB release pipeline, and only then reuse reservation/download/staging.
Also needed: a follow-up policy to search again after NO_MATCH for unaired or
not-yet-indexed episodes, and UI review/action controls.

The source changes and offline cases (window filtering, deduplication,
read-only provider queries, auth/privacy, v10/v6/v23 conversion and rollback)
are authored but **unexecuted** under project policy. No CI, HTTP calls,
downloads, browser checks, database upgrades, services or media were touched.
