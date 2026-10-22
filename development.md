# Anime Discovery — NextGen development handoff

> **Authoritative architecture decision: 2026-10-22.** NextGen is built fresh in `src/nextgen/`. There is **no migration**, compatibility bridge, legacy SQLite reader or transitional data assembler. Legacy `src/legacy/` is reference material for domain lessons and regression tests only.
>
> **Operational guardrails:** Draft work on branches/PRs; do not merge, deploy, restart services, change production databases, acquire/delete torrents, or touch user media without explicit authorization. Use `develop` as the PR target and verify CI before proposing merge.

## What is canonical

**Series schema, not processing state.** NextGen uses one versioned `AnimeSeries v1` schema (`src/nextgen/schema/anime_series.py`; detailed RFC at `src/nextgen/schema/README.md`). The series describes **the anime and its episodes**. It MUST NOT include webhook notification IDs, traces, GUIDs, source release names, job IDs, retries, acquisition, staging, evaluation, or export status. That information lives in independent durable operational records connected to the series after identification.

The identified series's required fields are:
- `anime.anidb_id`: positive AniDB anime ID (anime and sequel/cour identity).
- `anime.tvdb_series_id`: positive TVDB **series** ID for Sonarr.
- `anime.title`: nonblank **identified anime title**, not the original release name.
- `episodes`: one or more individually identified episodes.
- `episodes[].anidb_episode_id`: positive exact AniDB episode ID, including Shoko needs.
- `schema_version`: exactly `1` until a new schema version is approved.

Other series descriptors (alternative/original titles, year, anime type, AniDB episode display numbers, episode title/type, optional `episodes[].tvdb_placement` and `attributes`) are nullable or optional. TVDB *episode-level* IDs and per-episode TVDB season/episode mapping **are not hard identity-completion requirements**. Known placement is represented as `{season, episode}` inside the episode, with season 0 permitted for specials. AniDB episode numbering MAY be continuous or nonstandard. Never infer TVDB season from AniDB ordinal, default unknown to S01/E01, or conflate separately cataloged AniDB sequel entries under one TVDB series.

Every published series MUST satisfy a uniform, machine-checkable schema; optional fields normalize to null/empty object to spare future consumers missing-key crashes. Field docs track meaning, reason, owner, availability, and origin. Breaking changes require explicit schema versioning and permanent offline fixture tests. Structured optional attributes never override the core named fields.

### RFC-IDENTITY-001: mandatory completion gate

**This gate is at the END of identification, not at the webhook and not at some later acquisition stage.**

- The identification component gathers information in its own *incomplete* work state. An unrecognized anime, absent TVDB series link, or missing AniDB episode ID is **not** a completed series.
- Before changing work state to **IDENTIFIED/COMPLETE**, the identity component MUST validate the full candidate via `AnimeSeries.from_dict` (or the equivalent strict schema checker). Only a passing result may be saved/published as the authoritative series and referenced by downstream work.
- Failed validation MUST prevent identification from being marked complete and MUST block downstream acquisition. Persist a reason-coded, traceable **INCOMPLETE_IDENTITY** or **INVALID_IDENTITY** outcome in operational job history. The identity work MAY retry when information improves, or enter review. A failed candidate is a normal per-item outcome; it MUST NOT crash workers or lose the original webhook notification.
- A completed series's identity can be read without repeated identification by downstream components. Components still enforce their own **separate**, integration-specific prerequisites (e.g. exact TVDB episode placement before the NFO/episode import operation that needs it, file ownership/path verification at use time). The RFC is not authorization to acquire or export.

## NextGen processing components

Explicit static components, each with narrow responsibility:
1. **Webhook intake:** accept each authenticated, reasonably bounded delivery, retain the supplied release name as-is and write the delivery durably. No anime/episode/GUID/name-based deduplication here. Deliveries are observations, not series.
2. **Identity and cache:** resolve identified AniDB anime + exact AniDB episode(s), real title and TVDB series link. Reuse previously established cache evidence when applicable, while checking it applies to each input. No provider scoring/voting system and no assumption that altered title means new anime. The **identity gate** validates before marking done.
3. **Canonical episode claim:** once an exact episode identity exists, atomically determine if work for that episode has already been claimed/handled, preventing duplicate acquisition under parallel submissions. Preserve every source delivery and trace history.
4. **Acquisition:** own torrent operations, torrent identity/ownership, configured size limits, and Japanese + English audio checks. Do not infer identity from an acquisition job.
5. **Staging/Jellyfin:** own staging files and NFO output; require necessary TVDB placement for the particular operation and validate path/filesystem ownership at the moment of use.
6. **Human review and Sonarr export:** explicit Keep or Reject; exact export is never authorized merely by staging or by an identified series. Preserve existing hard-won mapping and safe import semantics, without linking runtime legacy code.

The coordinator owns bounded durable scheduling, not business-logic decisions. Logging/history uses stable per-delivery Postfix-style `AD-N` trace IDs and independent job IDs, *outside* AnimeSeries. Store structured durable history with safe reason codes, retries, cache activity and component boundaries; protect credentials and other sensitive data in logs.

## NextGen tests: fresh, local batches, no automatic GitHub checks

The clean-slate code uses its **own** tests in `src/nextgen/tests/`. The legacy tests in `src/legacy/` are preserved for history and regression behavior, but MUST NOT gate or be imported by NextGen implementation. The legacy tests need not inherently fail; they simply validate a different runtime.

The automatic GitHub Actions **Python test workflow has been removed** on this draft PR branch. Do not automatically run legacy or NextGen tests on pushes or pull requests. Keep the separate manually invoked archive publishing workflow unchanged. If branch protection requires a deleted check, resolve that repository rule explicitly before merging; do not silently bypass it.

Use `python -m src.nextgen.tests.run_batches --match schema` for focused schema work, or `python -m src.nextgen.tests.run_batches` for all NextGen tests, executed in separate groups of up to five test files. Use `--batch-size N`, `--match <filename-part>`, and `--list` as needed. This needs Python 3.12+ and runs **locally/on demand**, never against live services. See `src/nextgen/tests/README.md`. Each new NextGen component gets its own isolated offline tests and sample data in the existing `fixtures/` folder. Before a review/merge, run and document the relevant batches and the complete NextGen suite; no GitHub status check substitutes for this evidence.

## Next PR: delivery and worker reliability (TCP-like, application-level)

**Primary goal:** a webhook receipt that got HTTP success must not disappear or be silently unprocessable after a crash. TCP is an analogy for acknowledge/retry/recovery; do not promise literally failure-free or exactly-once execution.

Scope:
- Fresh standalone NextGen webhook handler, authenticated/validated/size-bounded, plus **fresh** SQLite durable inbox. Acknowledge successful submissions only **after** durable commit.
- Commit both the delivery record and its pending identity work marker atomically. This may be one inbox row with `PENDING` status; do not assume a separate executable job row per webhook is required.
- Bounded processing, leases or recoverable claims, retry/backoff on temporary failure, explicit permanent-error/manual-review state, graceful backpressure/retryable HTTP responses under overload.
- Every accepted delivery remains independently traceable; no content-based deduplication at intake. Identity caching and *post-completion* episode claims are separate later work. Nothing in the series schema tracks retries, attempts or delivery receipt.
- Offline fault-injection and concurrency tests: 10,000 requests with duplicate or changed release names, process death between commit and acknowledgment, crash during work, SQLite failure, restart recovery, provider unavailable, poison payload, duplicate acquisition claim protection (when built), log correlation, and bounded resource usage.
- No production changes, no real provider integrations, no live acquisition, no Jellyfin/Shoko/Sonarr side effects and no migration of legacy data.

Failure semantics: **accepted does not mean identified; identified does not mean acquired.** A validation failure fails *that identification attempt* cleanly. System-wide crashlessness is a design target, not an absolute guarantee; persistence, recovery and visibility are testable service invariants.

## Regression expectations and PR boundaries

Preserve domain behaviors as test cases, not code bridges: AniDB versus TVDB sequel/cour disagreement, Re:ZERO's verified mapping and exact episode references, season zero/specials, multi-episode releases, ambiguous or duplicate mapping, missing provider data, safe file ownership, dual audio, and explicit human approval.

- **PR #89:** closed without merge, superseded.
- **PR #90:** independent optional backfill design, **not** automatic backfill for NextGen.
- **PR #91:** draft exploratory traces/docs from legacy; outdated migration suggestions are superseded. Do not merge a stale handoff.
- **PR #92:** draft, offline-only AnimeSeries v1 schema and RFC identity-completion tests. No NextGen deployment or background worker included.

The next focused PR implements **durable intake/reliability infrastructure**, not the identity provider algorithm or media integrations.