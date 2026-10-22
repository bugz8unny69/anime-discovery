# AnimeSeries v1 — RFC-style series identity schema

**Status:** draft for review on PR #92; offline-only. **Version:** 1. This schema is independent from the production application and from the NextGen scheduler.

## Scope

`AnimeSeries` describes **the identified anime series and its episodes**, not how the application processed a webhook. The schema contains **no** notification ID, trace ID, release name, source GUID, retry state, acquisition, staging, Keep/Reject, export status, or job ID. These live in separate operational storage, connected to an identified series only after identity resolution. Multiple deliveries may link to one identified series; the identity component/cache and post-identification episode claimant own reuse and duplicate decisions.

AnimeSeries v1 is a **completed identity schema only**. A webhook is not expected to produce one directly. The identification component may accumulate partial evidence in its own work state and MUST call the schema parser/validator when it attempts to mark identity **COMPLETE**.

## RFC-IDENTITY-001 — identity completion gate

- Identity MUST populate `anime.anidb_id` with a positive AniDB anime ID.
- Identity MUST populate `anime.tvdb_series_id` with a positive TVDB **series** ID (not an episode ID), for Sonarr series identity.
- Identity MUST populate `anime.title` with the identified anime title, **not the webhook release name**.
- Identity MUST identify at least one episode. Every `episodes[]` item MUST populate a positive `anidb_episode_id`, for precise AniDB/Shoko episode identity.
- Identity MUST NOT publish a `COMPLETE` result or allow an acquisition handoff if the series fails those requirements or the versioned schema. The job MUST instead record an explicit incomplete/invalid-identity outcome, a reason and traceable history; it MAY remain retryable or await review. Invalid data MUST NOT crash or stop the entire service.
- Field types MUST be checked; unknown schema fields and incompatible versions MUST be rejected, not silently reinterpreted.
- Empty optional information MUST be safe: absent optional fields normalize to `null`, and absent `attributes` normalizes to `{}`. No component MAY silently invent a season number, episode number, AniDB ID or TVDB ID.
- The schema is the authoritative **description of the identified series once completed**. Original release names are accepted as received and used as identification input; there is no provider voting or generic truth/trust scoring mechanism.
- An AniDB anime ID may represent one sequel/cour entry while the same TVDB series groups several AniDB anime entries. Never assume a TVDB series ID uniquely determines AniDB anime ID, TVDB season, or episode placement.

## Fields

| Path | Requirement | Meaning |
| --- | --- | --- |
| `schema_version` | MUST equal 1 | Schema version |
| `anime.anidb_id` | MUST | Exact AniDB anime identity |
| `anime.tvdb_series_id` | MUST | TVDB series-level link for Sonarr |
| `anime.title` | MUST | Real identified anime title |
| `anime.english_title`, `anime.original_title`, `anime.type`, `anime.year` | MAY be null | Additional anime series descriptors |
| `episodes` | MUST have at least one | List of identified episodes, not workflow jobs |
| `episodes[].anidb_episode_id` | MUST | Exact AniDB episode identity for Shoko |
| `episodes[].anidb_episode_number` | MAY be null | Descriptive AniDB numbering; an integer or e.g. `"S1"`, never used to infer season |
| `episodes[].title`, `episodes[].type` | MAY be null | Episode descriptors |
| `episodes[].tvdb_placement` | MAY be null | Optional `{season, episode}` pair when actually identified |
| `attributes` | MAY be `{}` | JSON-compatible, documented additional series metadata; MUST NOT be used for processing state or override canonical fields |

When `tvdb_placement` is present, its `season` MUST be a nonnegative integer (0 is allowed for specials), and `episode` MUST be a positive integer. It is **not** required for identity completion. **Downstream operations** such as particular Jellyfin NFO formats or exact Sonarr episode imports MAY require more evidence and MUST stop safely when they lack that evidence. That is a downstream integration prerequisite, **not** a new mandatory episode-level TVDB requirement in this RFC.

Every serialized episode has the same field names after parsing/normalization; omitted optional fields are represented as `null`. Field-level machine-readable documentation includes meaning, reason, owner, availability and origin. Incompatible future changes MUST use a new schema version with regression fixtures; the unmerged draft v1 is being corrected before approval.

## Examples and offline tests

- `src/nextgen/tests/fixtures/anime_series_v1_verified.json`: identified series/episode and optional exact TVDB placement.
- `src/nextgen/tests/fixtures/anime_series_v1_continuous.json`: two known AniDB episodes, including continuous numbering and a special, with **no** TVDB episode placement.
- `src/nextgen/tests/test_anime_series_schema.py`: validates required fields, version, null-safe optional fields, uniqueness, two different AniDB anime records sharing a TVDB series, and an invalid completed identity failing cleanly.

## Next PR — reliability infrastructure, *not* identity provider implementation

Treat the user’s TCP analogy as **reliable delivery and recovery properties at the application boundary**, not a claim that TCP alone guarantees processing.

1. Build **fresh NextGen** authenticated, bounded webhook intake and SQLite-backed durable inbox in `src/nextgen/`, with no dependency on the legacy database or runtime.
2. Every accepted webhook delivery MUST be recorded individually; no GUID/name/content-based deduplication at intake. HTTP success MUST occur **only after** durable acceptance commits. Transient write/backpressure failure MUST return an explicit retryable HTTP error, not false success.
3. Use one atomic durable handoff to record an accepted delivery and its **pending identity work** (e.g. inbox status), avoiding an acknowledged-but-unprocessable gap. Whether a separate job row is created immediately is an implementation detail, not a series schema field.
4. Reclaim orphaned work after restart, bounded workers, leases and retry/backoff on transient failures; log persistent events and clear failure reasons, provide terminal/manual-review outcomes for poison requests rather than infinite hot loops.
5. Test burst submission (including 10,000 distinct or identical release names), concurrent writers, failed writes, process crashes, restart recovery, acknowledgments, retries, and end-to-end visibility. Keep only one acquisition claim after exact verified identity—this is **later**, separate from intake.
6. Scope is infrastructural: no live deployment, no actual provider calls, no acquisition, no Sonarr/Jellyfin/Shoko writes and no merger into the legacy runtime.

**Reliability goal:** no *acknowledged* event silently lost and no single bad identity record taking the pipeline down. Perfect availability, exactly-once processing and immunity to physical data loss cannot be guaranteed; make failures observable and recoverable instead.
