# Backfill and continue: intended behavior

This document supersedes the automatic backfill registration and waiting policy
in the older Sonarr acquisition checkpoint. It describes automatic Intake
acquisition, not the separate, explicitly requested **Keep in Sonarr** import.

## Episode selection

Backfill means acquire missing episodes numbered 1 through X of the selected
season. X is an episode-number boundary, not a quota of X additional downloads.
Continue selects the configured range starting with the incoming episode.
The current `trial.following_count` includes that incoming episode.

The two ranges are a union: overlapping episodes count once. For example,
backfill=6, incoming episode=5, following_count=3 selects episodes 1–7, with
5 and 6 present only once. An existing active reservation skips a second search
and acquisition for that episode, including reservations made by batch jobs.
Existing Sonarr episode files are skipped. The existing local reservation and
acquisition pipeline remains responsible for preventing duplicate ownership.
Backfill=0 disables backfill; both counts zero is invalid. Existing frozen plans
retain their captured settings and season. Continue admits subsequent incoming
releases in that window; this fix does not introduce a future-episode polling job.

## Search and download responsibilities

1. Read Sonarr's version, matching series and episode records using GET.
2. For an unreserved, missing episode with a Sonarr episode ID, GET interactive
   releases and wait for that request to return.
3. Select by the existing episode mapping, resolution and seeder policy.
   Sonarr profile rejection alone does not exclude an otherwise usable torrent.
4. Read a magnet from `magnetUrl` or a magnet-valued `guid` (including Nyaa GUIDs).
   Extract its hash when needed; conflicting hashes are not silently accepted.
5. Pass the candidate through the existing verification/acquisition pipeline
   to qBittorrent. qBittorrent downloads; Anime Discovery stages the result.

Automatic backfill must NEVER add a Sonarr series, modify monitoring, request
RefreshSeries/scan/import, POST a release grab, or ask Sonarr to download/manage
these files. The discovery client is GET-only. No Keep client is called by
backfill. Already-created Sonarr series are not deleted by this fix.

## Immediate, truthful results

- A missing series or requested episode record stops the current page immediately
  with a specific error. There is no two-minute delay, ten-attempt listing loop,
  implicit series creation, or assertion that Sonarr is refreshing.
- A transport timeout produces `SONARR_DISCOVERY_TIMEOUT` immediately when the
  request raises it. Other connection/service failures produce
  `SONARR_DISCOVERY_UNAVAILABLE`. Neither schedules an automatic retry.
- Release GETs retain the 180-second transport timeout; catalog requests use
  `sonarr.timeout_seconds`. This is a per-request socket timeout, not a shared
  180-second deadline for an entire multi-episode page.
- These errors use the existing BLOCKED state and HANDLER_FAILED history event.
  The operator can Retry the same job or Cancel. No successor is created on error.
- A page publishes its selections atomically. If any requested, unreserved
  episode is unlisted, that page fails without publishing partial selections.
  Previously completed pages and other intake/continue jobs remain intact.
- Existing delayed jobs adopt this behavior on their next eligible attempt.
  Historical ON_HOLD jobs are no longer automatically restarted by recovery.
- Logs show the requested TVDB series, season, episode range and reservations,
  each GET start/response duration, and missing episode numbers. No API keys,
  magnet links or full response payloads are logged.

## Sonarr API limitation: not solved by waiting

Sonarr v4's `/api/v3/release` controller searches an existing `episodeId`, or an
existing `seriesId` plus `seasonNumber`. Without those search parameters it
fetches RSS; it is not an arbitrary title/TVDB torrent search. See
[Sonarr's controller](https://github.com/Sonarr/Sonarr/blob/main/src/Sonarr.Api.V3/Indexers/ReleaseController.cs).

Consequently, this adapter can search existing catalog episodes without mutating
Sonarr, but cannot backfill an unregistered show or an empty episode catalog.
Supporting those requires a search source independent of Sonarr's catalog (for
example an explicitly implemented indexer/Prowlarr adapter). This fix does not
claim that empty catalogs can now acquire releases, nor invent episode IDs or
silently change providers.

## Scope boundary

The existing user-triggered **Keep in Sonarr** feature still imports/manages
permanent media through Sonarr. It is outside automatic backfill and has not been
removed or redefined here. A global ban on Sonarr writes would also require
replacing that separate feature; do not describe this patch as a global ban.

## Local verification

Regression tests cover no registration, missing episodes (including overlap with
an active reservation), immediate timeout/service errors without successors,
manual retry of the same stopped job, GET-only release transport, GUID magnets,
and the overlapping backfill/continue window. Existing acquisition/handoff tests
cover candidate dispatch. Tests use fake transports, not the operator's services.

Validation on 2026-10-29 (Python 3.12):

- Final focused suite: 81 tests passed (backfill, discovery, trial selection,
  manual retry, and Sonarr handoff).
- Dashboard browser suite: 14 tests passed; Python compilation, installer
  compilation, JavaScript syntax and `git diff --check` passed.
- Full local NextGen suite: 23 of 25 batches passed. The only two errors were
  `test_local_password_setup_and_rotation` and `test_delivery`: this execution
  environment denies AF_UNIX socket creation with `PermissionError`. Tests were
  not skipped or weakened. No live homelab test was performed.
- One feature-branch commit with `[skip ci]`; no PR or workflow dispatch is
  required. The repository's push CI trigger targets only `NextGen`.
