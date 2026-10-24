# Anime Discovery NextGen — architecture

**Canonical product flow:** **Intake → Evaluate → Download → Verify → Stage → Review → Keep or Reject.**

NextGen receives releases from **autobrr**, evaluates the submitted episode, downloads eligible media with the existing acquisition pipeline, verifies it, and stages a review copy. A reviewer explicitly selects **Keep** or **Reject**. Keep imports through Sonarr with exact TVDB episode mapping; Jellyfin library refresh is independent; Shoko is optional and must not block Keep.

**Out of scope:** built-in anime search, Prowlarr, indexer discovery, automatic searches for unreceived episodes, a Legacy runtime dependency, or a second intake pipeline. The configured episode window determines eligibility for *received and verified* episodes; it is not an instruction to search elsewhere.

## Design references

1. [Intake through staging](INTAKE_TO_STAGING.md) — process ownership, exact identity/release validation, download, media verification, safe staging and review.
2. [Episode selection policy](../EPISODE_SELECTION_POLICY.md) — backfill/following windows applied only as eligibility policy.
3. [Keep to permanent library](KEEP_TO_LIBRARY.md) — authorized Sonarr copy import, journal, verification and follow-up cleanup.
4. [Mandatory human-readable messages](../HUMAN_READABLE_MESSAGES.md) and [reason codes](../REASON_CODES.md) — every emitted marker and error has a central English explanation and stable translation key.
5. [Job contracts](../jobs/README.md) and [configuration](../CONFIGURATION.md) — worker contracts and versioned persisted settings.

## Processing boundaries

Intake durably accepts a delivery; it does not declare the release correct. Verification uses AniDB for anime/episode evidence and TVDB for Sonarr-compatible identity. The worker owns job lifecycle and atomically commits each validated job completion, associated facts, history and allowed successor jobs. A completed job is not necessarily a staged video or completed Keep.

Staging preserves downloaded source content; a successful stage creates reviewable copies/metadata. Keep is an explicit later action, never an automatic consequence of intake. Reject blocks future acquisition of that AniDB anime according to the recorded decision and cleans only authorized staged artifacts. Uncertain imports never authorize blind command replay or cleanup. A Jellyfin scan request does not prove indexing completed.

## Naming and compatibility

**Use “staging”, “review”, and “episode selection” in new product copy, documentation, and APIs.** Older persisted machine identifiers in the configuration, database, job kinds, reason codes, and historical links are compatibility contracts: they must not be renamed without a separately designed migration. Existing source modules carrying previous names may remain until a controlled, versioned rename. Present English messages through the shared message catalog, not by mechanically displaying internal identifiers.

## Implementation and validation status — 2026-10-24

As of the draft stack through [PR #130](https://github.com/bugz8unny69/anime-discovery/pull/130), intake, acquisition, media verification, staging, Reject, journaled Keep → Sonarr, and independent Jellyfin scan handoffs have draft implementations. They are **not validated end to end**, merged, or deployed as a finished product. Optional Shoko, post-Keep cleanup/recovery, startup supervision, and lab integration remain incomplete. The earlier architecture proposals are preserved in Git history; this page and its linked documents describe the current agreed direction.
