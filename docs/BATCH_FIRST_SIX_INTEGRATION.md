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


## No-intervention automation policy (explicitly required)

Normal Nyaa/Autobrr ingestion **must not require clicking Resolve**.
Operator review is a fail-closed last resort for genuinely contradictory
provider identities, unsafe or irreconcilable file lists, or verified-audio
failures requiring a policy choice. Invalid/out-of-scope media should be
automatically excluded with an explicit reason, without staging or starting a
download. This includes `S00` movie/special releases under the current
strict positive-season, first-six policy.

Nyaa names require deterministic, safe normalization **before** sending
title queries to AniDB and TVDB. For notification #4, the *only* direct
series query should be `Cyberpunk Edgerunners`; technical `Season S2`,
`Batch`, `1080p`, `AV1`, and `WEB-DL` are not query aliases.
The configured 90% title threshold stays in place. Count only candidates
that pass the title filter as meaningful ambiguity, then demand canonical
TVDB/AniDB cross-reference evidence. Metadata `S02` is a hint, not proof
that a verified provider has a corresponding season; do not silently
reinterpret it as S01. A verified series title alone does **not** authorize
download of a batch with unmapped episode files.

### Next integration steps for zero-touch flow

- Persist a **series-level identity decision** independently of episode
  mapping so batches can add an owned magnet normally, collect its file list, and immediately pause before applying file priorities.
  Introduce durable states such as `WAITING_FILE_MANIFEST` and
  `EXCLUDED_OUT_OF_SCOPE` rather than reusing the single-episode approval.
- For a verified multi-file batch, add the torrent in the Anime Discovery
  category with its ownership marker and let it start. Poll `torrents/files`
  about once per second; as soon as the manifest is available, pause that
  exact torrent. Plan E01 first, set and verify all file priorities, then
  resume. Never proceed if the manifest, indices, ownership, or priority
  readback cannot be verified.
- The new `QBittorrentAPI.apply_stopped_file_selection()` is currently
  **not wired to the worker**; it rejects running/unowned torrents and
  checks that selected/skipped indices cover every file. Tests only, no
  live torrent touched. Caller must also verify ownership in the database.
- Model per-episode outcomes under one torrent, with individual ffprobe and
  idempotent Jellyfin import. A single audio failure must not invalidate
  other independently verified episodes.
- On deployment of a new resolver, re-triage terminal review notifications
  from known old parser defects **automatically and at most once**,
  preserving notification IDs, prior evidence, existing ownership, and
  any completed downloads. Do not silently repeat external acquisition.
- Notification #3 should be excluded as a season-zero special rather than
  requiring user approval for an ordinary six-episode trial. A separate
  deliberate movie/special workflow can be added later if desired.


## E01-first gated acquisition (2026-10-20 refinement)

Operator's preferred bandwidth-saving sequence: **first E01 only**, use
the *completed* E01 file as the Japanese+English ffprobe gate, and only if
it passes allow **E02-E06 (five more)** from the same pack. All later files
remain unwanted. Verification of the sample episode does not prove the
remaining episodes have identical audio; each selected file still needs its
own post-completion ffprobe and idempotent staging. One torrent can contain
ten/twelve episode videos while only six are wanted.

A pure `plan_gated_first_six()` function now models the probe and unlock
phases. It does NOT act on qBittorrent, mark the probe verified, authorize a
resume, or persist the gate; the actual worker integration remains to be
built. Probe authorization must come from durable (torrent hash, file index,
series identity, episode) evidence and a successful ffprobe check, not a
webhook, release title, or a 100% torrent-progress indicator.

**Critical implementation constraints:**

- **Metadata bootstrap (simple by design):** Add the verified, tagged
  magnet normally (running) to qBittorrent. Poll the file inventory every
  ~1 second. Once a complete usable file list exists, immediately pause
  that exact torrent, wait for its stopped state, then select E01 and set
  all other file priorities to zero. This initial discovery window can
  download some real video pieces, not just torrent metadata. That small
  temporary over-download is acceptable to the operator; there is no
  guaranteed byte ceiling or assumption it will always be negligible.
  If metadata is slow or empty, retry polling later without creating
  duplicate torrents. Do not build a separate metadata-only downloader.
- **Phase 1:** With the complete verified manifest, set only E01 priority=1
  and all other files priority=0, read back priorities, then authorize a
  guarded torrent start. A BitTorrent piece can straddle file boundaries,
  so negligible shared-piece data from skipped neighbors is possible.
- **Phase 2:** Once the selected E01 index reaches 100% and the on-disk
  file is complete and stable, ffprobe Japanese+English; bind the result to
  exact torrent/file provenance in the database. Stop the torrent, widen
  wanted indices to E01-E06, read back priorities, then start again.
  qBittorrent may report `stoppedUP`/`pausedUP` after E01 finishes,
  because only E01 was selected. Adapter now recognizes stopped upload
  states, but this priority transition is **only tested with fake transport**.
  Verify the installed qBittorrent/libtorrent version accepts new wanted
  priorities after subset completion; if it does not, devise a safe
  alternative and do not start or download extra files.
- **Fail closed:** No E01 in pack and no other verified E01 available:
  search for a trusted single-episode E01 candidate; do not substitute
  random E02/E03 as equivalent identity evidence. A failed language probe
  must not unlock anything. Never duplicate acquisition or stage partials.
- **Simple recovery:** Persist the torrent hash, the verified identity,
  whether E01 passed audio verification, and completed trial episodes.
  After a restart inspect qBittorrent's existing torrent instead of adding
  a duplicate. Poll delayed metadata without requesting user intervention;
  contradictory identity/file data still fails closed.


## Installed qBittorrent compatibility target (Debian 12)

Production package reported by operator:
\`qbittorrent-nox 4.5.2-3+deb12u1\`. Do **not** require a qBittorrent
upgrade for progressive E01-first trial sampling.

The server's actual \`GET /api/v2/app/webapiVersion\` value (not the Debian
package suffix) determines endpoint behavior. Our offline adapter
\`QBittorrentAPI.web_api_version()\` requires Web API >=2.8.2 and <3.0
for reliable \`torrents/files\` \`index\` and \`filePrio\` support:

- Web API <2.11.0 (qBittorrent 4.5.2): \`torrents/add\` with \`paused=true\`,
  \`torrents/pause\` and \`torrents/resume\`; stopped states are
  \`pausedDL\` and \`pausedUP\`.
- Web API >=2.11.0 (qBittorrent 5.x): \`torrents/add\` with \`stopped=true\`,
  \`torrents/stop\` and \`torrents/start\`; stopped states are
  \`stoppedDL\` and \`stoppedUP\`.
- Both share \`torrents/files\`, \`torrents/filePrio\`, priorities \`0\`
  (not wanted) and \`1\` (normal), exact single-torrent hash operations,
  marker ownership checks and a complete file-priority readback.

These version-aware helpers (\`stop_owned_torrent\`,
\`start_selected_torrent\`, and \`add_magnet(..., stopped=True)\`) are
*not integrated in the running acquisition worker*. The worker MUST
verify durable DB-owned provenance in addition to matching tag/category,
hold the relevant lease, preserve selected-E01 audio evidence, and only
resume once the complete manifest is validated.

**Metadata bootstrap policy:** No special metadata-only service is needed.
Add the torrent normally after identity verification, poll for the file list,
and immediately pause the torrent before selecting files. Some payload pieces
may download during discovery; that is an accepted, bounded-by-response-time
tradeoff, not a guarantee of only a few bytes. If a torrent finishes unusually
quickly, still pause it and apply file selection before continuing; do not
assume that unselected content was never downloaded.

Testing is currently synthetic/fake Web API transport. Before deploying,
check the actual \`app/version\` and \`app/webapiVersion\` read-only,
and verify \`pausedUP\` transitions and file-priority effects on a
disposable isolated 4.5.2 instance. Never use existing torrents as tests.

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

1. **Torrent intake:** Add new, verified magnets running with Anime Discovery
   category and durable ownership marker. Poll every ~1 second for the file
   list, then pause the exact torrent immediately when it appears. Allow
   limited incidental payload while fetching metadata. Never change an
   unowned or pre-existing torrent. If metadata is delayed, retry the
   existing hash later without creating duplicates.
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
controlled local torrent client fixture; verify that E01 is selected
first and E02-E12 have priority zero during the E01 probe. After E01 passes,
E02-E06 unlock and E07+ remain priority zero. Observe and accept incidental
payload transferred in the short metadata discovery window; ensure no
further unwanted files are downloaded after reprioritization. Separately use actual ffprobe-readable fixture media to check
Japanese+English streams and mixed-audio failures. Verify the qBittorrent
client version/behavior before any production trial. Check retries and
restart idempotency. No live job should be retried until this integration
is complete.
