# Batch-aware first-six planner: integration contract

Status: **planner and offline tests only**. NOT DEPLOYED, NOT CONNECTED to
the acquisition worker. Branch must not be treated as production batch support.

## Confirmed development baseline issues

- `anime_release_matching.resolve_release` requires a release-level episode.
- `anime_media_completion.verified_media` requires exactly one file.
- `anime_claimed_pipeline.process_claimed` operates on one approved episode
  per notification, demands overall torrent completion, then stages once.
- `anime_qb_api.QBittorrentAPI.torrent_files` can enumerate files, but there is
  no implemented priority modification endpoint.
- `anime_shared_discovery.search_once` scopes by season but does not cap
  all Prowlarr candidates at episode 6. `anime_webhook_processing.approve`
  does not enforce the six-episode ceiling.
- `anime_audio_verification.confirmed_jp_en` probes actual audio tags and
  must remain a separate gate for *each* eligible selected file.

These findings are source-audit observations, NOT diagnoses of the two live
queued items. Their database rows/logs and torrent hash ownership must be
examined before mutation.


## Production observations supplied 2026-10-20 (read-only screenshot)

The Anime Discovery Jobs/Acquisition Activity page shows two `NEEDS_REVIEW`
**notifications**, not two acquisition jobs. The dashboard explicitly says
"No acquisition job was created" for each. Neither qBittorrent ownership nor
live torrent existence was checked.

- **Notification #4:** `[Trix] Cyberpunk Edgerunners S02 ... (Season S2) (Batch)`.
  The release suggests a season-2 pack but provides no single episode number.
  Identity report: `EPISODE_NUMBER_UNRESOLVED`,
  `NO_ANIDB_EXACT_TITLE_MATCH`, `AMBIGUOUS_TVDB_CANDIDATES`.
  Needs confirmed TVDB/AniDB series identity, a safe stopped torrent
  manifest, and per-file episode verification. Do not manually approve as a
  single episode: that could download the complete torrent under the old path.
- **Notification #3:** `[Anime Time] KonoSuba ... S00E05 - Movie Legend Of
  Crimson ...`. This is explicitly season zero, not S01E05. Identity
  report: `EPISODE_NUMBER_UNRESOLVED`, `NO_ANIDB_EXACT_TITLE_MATCH`,
  `NO_TVDB_SEARCH_RESULTS`. Keep outside ordinary E01-E06 trial sampling;
  a separate explicit specials/movie policy would be needed.

The `release_scope_hint` diagnostics are *non-authorizing*. Old notifications
already in terminal Needs Review will not automatically be re-evaluated merely
because this feature branch is merged. Design a reviewed, idempotent re-triage
action that preserves notification ID and avoids torrent resubmission.

## Planner

`anime_batch_selection.plan_first_six(files, season=N, already_satisfied=...)`
expects a complete qBittorrent `torrents/files` manifest with exact file
`index` and relative `name` keys. Confirm TVDB/AniDB identity and the
**discovered season** before calling it. It returns wanted/skipped indices
and an episode-to-file-index map. It does not infer series identity, mark a
job approved, or alter a download. It deliberately refuses missing episode
numbers, mixed seasons, multi-episode files, duplicate episode mappings,
unsafe paths, and incomplete manifests. No guessing from the `Batch` tag.

## Required before integration

1. **Torrent intake:** New magnets must be added stopped/paused, preserving
   ownership fencing. Magnet metadata can arrive asynchronously; keep the
   torrent stopped while polling for its manifest. Do NOT apply this flow to
   an already-running or non-owned torrent. On timeout or empty manifest,
   Needs Review; do not resume a full pack.
2. **Atomicity:** Before resuming, set unwanted file priorities to zero and
   verify every file index's effective priority with a fresh manifest.
   qBittorrent Web API uses `torrents/filePrio` with `hash`, `id`,
   `priority` (0 means do not download); adapt to the verified installed
   qBittorrent version. Do not assume a mutation acknowledgment means the
   priorities took effect. Keep safe failure stopped, needing review.
3. **Data model:** One torrent notification must be able to own many
   distinct (series, season, episode, file index) records with per-file
   probe/import/review status. Migrate with backup and rollback; preserve
   existing single-episode rows and durable ownership markers.
4. **Bounds:** Put E01-E06 enforcement at final approval and search intake,
   not only in this planner; never let a legacy queued E07+ bypass it.
5. **Completion:** qBittorrent reports overall progress based on wanted
   files. Ensure selected files individually have progress=1 and reside
   within a verified download root; check ffprobe JP+EN on each file before
   staging. A mixed-audio pack cannot be accepted wholesale.
6. **Duplicates & ownership:** Hold the selected per-season episode
   reservation transactionally, avoid duplicate imports, never overwrite
   existing verified files, and keep/reject paths must honor Sonarr ownership.
7. **Recovery:** An operator-confirmed TVDB mapping may retry against the
   same verified/owned downloaded torrent. Never make an untrusted torrent
   eligible for deletion, nor blindly reset historical queue state.

## Safe operational validation

Use a disposable torrent with 12 tiny media-like test filenames or a
controlled local torrent client fixture; verify that E01-E06 are selected,
E07-E12 have priority zero, and no data transfers until priorities are
verified. Separately use actual ffprobe-readable fixture media to check
Japanese+English streams and mixed-audio failures. Verify the qBittorrent
client version/behavior before any production trial. Check retries and
restart idempotency. No live job should be retried until this integration
is complete.
