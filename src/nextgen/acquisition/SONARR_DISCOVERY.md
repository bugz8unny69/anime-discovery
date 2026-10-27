# Sonarr interactive discovery — Batch 1

## Purpose

Reuse **Sonarr v4's** own indexer searching, parsing, quality/profile decision
engine, seed minimum checks, custom format scoring, and result prioritization.
NextGen's TVDB placement remains authoritative. No separate release scoring or
Prowlarr credentials are introduced.

Code:

- `src/nextgen/sonarr_episode.py`: pure, shared TVDB-to-Sonarr placement.
- `src/nextgen/keep_selection.py`: Keep now delegates to the same matcher.
- `src/nextgen/acquisition/sonarr_search.py`: read-only GET transport,
  normalized results, fail-closed episode mapping.
- `src/nextgen/tests/test_sonarr_discovery.py`: transport fakes and offline
  contract tests; **not executed** and not a substitute for runtime integration.

## Contract

Supply `VerifiedEpisode(tvdb_series_id, tvdb_episode_id, tvdb_season,
tvdb_episode)` **after** provider verification. The client uses existing
`sonarr.base_url`, `sonarr.timeout_seconds`, and the secret store's existing
`sonarr_api_key()`. Example for a trusted internal caller:

```python
from src.nextgen.sonarr_episode import VerifiedEpisode
from src.nextgen.acquisition.sonarr_search import Client

identity = VerifiedEpisode(tvdb_series_id=100, tvdb_episode_id=200,
                           tvdb_season=1, tvdb_episode=10)
client = Client.from_context(configuration, secret_store)
results = client.search(identity)
for candidate in results.candidates:
    print(candidate.title, candidate.quality, candidate.resolution,
          candidate.seeders, candidate.approved, candidate.rejections,
          candidate.scope, candidate.eligible_for_handoff)
```

**Do not print or log magnet URLs or credentials.** They may contain tracker
passkeys. `Release.magnet_url` is excluded from repr.

The client allows only four HTTP GET routes, in this order:

1. `system/status` — Sonarr major version must be 4.
2. `series?tvdbId=<verified ID>` — exactly one existing TVDB match.
3. `episode?seriesId=<existing ID>` — exactly one TVDB-compatible episode.
4. `release?episodeId=<matched ID>` — Sonarr's prioritized interactive
   episode search; ranking is preserved without re-sorting.

No POST, series registration, command, quality profile mutation, downloading,
or import exists in this adapter. An interactive GET does, however, contact
indexers and update Sonarr's internal last-search timestamp. Sonarr may
independently perform its own existing scheduled/RSS activities; this module
does not change those settings.

Results retain Sonarr's `approved`, `rejections`, resolution and quality,
custom format score, seeds/leeches, size, and mapped episode IDs. `scope`
is `exact`, `pack`, `mismatched`, or `unmapped`. Only an approved,
exactly mapped, torrent-protocol, single-episode release with a matching v1
BTIH hex magnet can set `eligible_for_handoff=True`. That flag is **only a
discovery hint**, not a download permission, audio verification, torrent
provenance proof, or an acquisition-plan authorization. Neither the flag nor
Sonarr approval bypass NextGen's independent checks.

Candidates without magnet hashes, indexer-only URLs, season packs, uncertain
episode mapping, or rejection details are retained for inspection but cannot
be handed to acquisition automatically. The adapter never fetches untrusted
`downloadUrl` addresses. The 4 MiB response and 1000-release bounds,
timeouts, no-redirect transport, and response validation fail closed.
Authentication, unavailable service, missing identity and malformed results
produce distinct errors.

## Excluded from Batch 1

- Automatic backfill/continuation worker scheduling and any retry timing.
- Automatically adding unregistered series to Sonarr or changing monitoring.
- Candidate reservations, torrent metadata resolution, Sonarr grab POST,
  qBittorrent submission, Keep, or cleanup.
- Dashboard/API exposure, config/secret migrations, CI, or production activity.
- Live indexer testing; actual client compatibility and release response
  variations still require controlled integration validation.

## Next decision point

Review real interactive Sonarr results in a controlled environment and verify
that mapped episode IDs, `approved`, magnet URLs and rejection reasons are
populated as expected. Next batch should schedule requested missing TVDB
episodes through the worker with deduplication and backfill window caps. Torrent
handoff requires its own separate ownership and metadata-verification design.
