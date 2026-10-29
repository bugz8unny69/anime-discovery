# Backfill and continue: intended behavior

Automatic backfill and continue search Prowlarr directly. Sonarr takes no part
in finding or downloading these episodes. The separate, user-triggered **Keep**
import is unchanged and still uses Sonarr.

## Episode selection

The searched window is the union of:

- backfill: episodes 1 through X of the verified TVDB season (`trial.backfill_count`);
- continue: the incoming episode and the following ones (`trial.following_count`
  includes the incoming episode).

Overlaps count once. The incoming episode itself is never searched: its own
delivery is already acquiring it. Example: backfill=6, incoming=5,
following_count=3 searches 1, 2, 3, 4, 6 and 7.

Episodes with an active reservation (single or batch) are skipped and reported
as `IN_PROGRESS`. Staged and kept episodes keep their reservation, so they are
skipped too. A canceled episode releases its reservation and is searched again.

Frozen plans keep their captured counts and season. The window is searched in
pages of four episodes; each page is one `DISCOVER_SONARR_BACKFILL` job (the
historical job and table names are kept so existing jobs and history stay valid).

## How an episode is searched

1. The episode catalog (`providers/backfill_catalog.py`) maps the TVDB episode
   to its AniDB episode number with the same cached AniDB record, Anime-Lists
   offsets and TVDB official episode list that VERIFY_RELEASE uses, and reads
   the AniDB air date.
2. Prowlarr is queried with GET `/api/v1/search` for up to three Latin-script
   AniDB titles plus the two-digit AniDB episode number
   (for example `Kusuriya no Hitorigoto 01`).
3. A result counts only when its title matches one of the anime's AniDB titles
   exactly (normalized) and declares exactly that episode, either as the AniDB
   number (`- 01`) or as the TVDB placement (`S02E13`). Batches, ranges and
   specials never match.
4. Resolution is read from the title (480p … 2160p, 4K/UHD). Releases without a
   resolution, above `prowlarr.max_resolution`, or below `prowlarr.min_seeders`
   are counted but not used. The rest are ranked by `prowlarr.rank_by`.
5. The magnet comes from `magnetUrl`, a magnet `guid`, or the `infoHash`
   (bare hash). Conflicting hashes drop the result.
6. The best release goes through the existing pipeline unchanged: an internal
   delivery is verified by VERIFY_RELEASE, reserved, sent to qBittorrent with
   its sanitized magnet, downloaded, verified and staged. Lower-ranked releases
   are kept as fallbacks if that acquisition fails.

## Results are reported per episode

| Status | Meaning |
| --- | --- |
| `CANDIDATES` | Matching releases found; the best usable one was sent on |
| `NO_RESULTS` | Prowlarr returned no matching release |
| `NOT_AIRED` | AniDB has no past air date, or TVDB does not list the episode yet |
| `MAPPING_MISSING` | TVDB lists the episode but the AniDB/TVDB mapping is missing or ambiguous |
| `IN_PROGRESS` | Already reserved, staged or kept |

One episode without releases never holds back the others on the page. A
Prowlarr failure stops the page at once, without publishing partial results and
without an automatic retry or idle loop:

- `PROWLARR_SEARCH_TIMEOUT` — a search exceeded `prowlarr.timeout_seconds` (BLOCKED, Retry available);
- `PROWLARR_UNAVAILABLE` — Prowlarr or an indexer failed (BLOCKED, Retry available);
- `PROWLARR_AUTH_FAILED`, `PROWLARR_CONFIGURATION_INVALID` — fix Settings, then Retry.

Not-aired episodes are reported, not polled. Continue still admits later
episodes when they arrive through the webhook.

## Settings

Settings → Prowlarr: address, API key, search timeout, maximum resolution,
minimum seeders and ranking. Configuration v11 moves the former
`sonarr.discovery_*` preferences there, keeping their values. Secrets v8 adds
the Prowlarr API key; older secret files stay readable.

## Known limits

- Releases numbered absolutely across seasons (for example `- 25` for a sequel
  whose AniDB entry starts at 1) are not matched, because VERIFY_RELEASE would
  not accept them either. Supporting them needs a matching verification change.
- Media that was already in the library before NextGen (no reservation) is not
  detected and may be searched again.
- No live homelab end-to-end run has been performed.
