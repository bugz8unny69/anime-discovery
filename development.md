# Anime Discovery — NextGen development guide

> **Architecture decision:** 2026-10-22. NextGen starts fresh. This is the authoritative development handoff for the *new* app, not a migration plan or an instruction to modify production.
>
> **Safety:** Never merge, deploy, restart services, migrate legacy SQLite, download/delete torrents, or alter staged media without explicit approval. Work in branches targeting `develop`. The old `src/legacy/` application stays operational and unmodified.

## What we are building

Build a new, **component-based Anime Discovery** in `src/nextgen/`, using one versioned canonical `ReleaseRecord` schema across the complete lifecycle:

1. **Autobrr webhook intake:** authenticate, bound/validate input, persist **each accepted delivery** as a distinct event and record its trace ID. The sender can change names, GUIDs and other fields. **Do not perform release-name, GUID, anime, or episode deduplication at intake.** Source/GUID are historical observations, not identity authority.
2. **Identity:** identify the **verified AniDB anime ID and verified AniDB episode ID**; independently verify the related **TVDB series ID, exact TVDB season and episode**, with mapping evidence. Prefer AniDB for anime identity; retain tested cross-provider mapping requirements. Do not infer episode equality, TVDB season 1, or a sequel/part/cour mapping from a title.
3. **Identity evidence cache:** reuse validated anime/episode evidence quickly on repeated submissions, while testing whether a new release actually matches cached identity. Cache keys/provenance must be grounded; a manipulated title or GUID is not proof. Bound simultaneous lookups and external-provider rate limits. Cache cannot replace verification.
4. **Canonical episode claim:** only **after exact identity has been verified**, check whether the episode is already claimed, acquired, staged, or kept. Implement atomic claim semantics so 10,000 deliveries do not create 10,000 downloads; preserve all notification histories separately. Define equivalence carefully for alternate releases and episodes.
5. **Acquisition:** enforce existing size, safety, torrent ownership, Japanese and English audio requirements. Never make a new acquisition decision based solely on an unverified incoming payload.
6. **Staging/Jellyfin:** use verified TVDB ID, season and episode for NFO and Jellyfin compatibility; use AniDB IDs/provenance where helpful. Revalidate source and destination paths, containment, symlinks, permissions, and ownership **at the moment of use**. Never trust a path because a schema field exists.
7. **Human evaluation:** the user explicitly chooses Keep or Reject; merely reaching staging never means Keep.
8. **Keep/Sonarr export:** use existing proven exact mapping and safe import behavior. Reject uses ownership-aware cleanup. **Do not defer TVDB reconciliation to this stage**: staging NFOs already require it.

## One canonical versioned schema

`ReleaseRecord v1` lives in `src/nextgen/contracts/release_record.py` on draft PR #92. This is **a new schema and storage design**; NextGen must **not** read or migrate production/legacy SQLite through a compatibility assembler. The old code is reference material for tested behavior, algorithms, integration contracts, safety failures and fixtures; there is **no data migration or old-to-new runtime bridge**.

- Keep a single structure throughout the pipeline. Intake creates initial fields; later components populate only their own sections, leaving not-yet-established values explicitly missing.
- Preserve **both** `identity.anidb_id` (anime identity) and `identity.anidb_episode_id` (exact AniDB episode identity), plus `identity.tvdb_id`, `identity.season`, `identity.episode`, and `identity.mapping_source` (mapping provenance). These values must be verified; no guesses or silent overwrites. Future additional stable provider episode IDs need their own documented contract changes.
- Keep `notification_id` / `AD-<notification_id>` as *delivery* and trace identities; `anidb_id + anidb_episode_id` and the separately verified TVDB relationship describe *content identity*. Many deliveries can point to the same verified content.
- Keep job identity, job attempts and identity cache provenance distinct from content identity. Stage outcomes require verified prerequisites; a schema instance itself is **not proof** that a provider verified it.
- Define field metadata for **meaning, reason, owner, available, trust** (machine-checkable, PHPDoc-like). Schema v1 fixtures and tests must remain available after future version changes. Breaking changes require a new version and explicit contract tests, never silent reinterpretation.

## Component boundaries and orchestration

Components are **static, explicitly called and independently testable**: Intake, Identity, Cache, Episode Claim, Acquisition, Staging, Review, Sonarr Export, and Observability. No runtime plugin discovery, dynamic hook registration, provider voting, or generic hook execution framework.

A thin job coordinator schedules bounded durable work, reloads validated canonical records, and persists each stage's result. Components own their data/logic; the coordinator does not make identity or media-safety decisions. A component needing private extra evidence changes internally; shared record changes require contract review and affected consumer tests.

Design **fresh NextGen job persistence**, borrowing proven ideas (SQLite transactions, idempotency, independent completion, leases, retries, failure recovery) from the old `anime_async_daemon.py`; don't copy or depend on the legacy runtime for production. Accept an intake request only after durable write. The implementation must sustain bursty intake through bounded queues, backpressure and controlled provider requests. A large backlog is not permission to skip or collapse incoming histories.

## Logging is core infrastructure

Use structured, sanitized, durable events and journal output with stable Postfix-like trace identifiers. Every stage and job start/finish, cache hit/miss, exact identity determination, episode claim, retry/review, safe reason code, staging result and Keep/Reject result should be traceable. Separate one delivery's trace from canonical episode grouping. Dashboard Activity/History must eventually expose copyable trace and job IDs and ordered history. Avoid leaking secrets, untrusted release payloads, credential URLs or unsafe paths. Journal rotation must not erase persistent activity history.

## Safety and regression contract

Prior code exposed important season-mapping problems. Preserve tested semantics from `src/legacy/test_anime_unified_identity_monitor.py`, `src/legacy/test_anime_episode_crossref.py` and related tests as **behavioral requirements**, not as migration wiring: correct AniDB-first sequel discovery, independent verified cross-reference, no automatic guessed season or episode, safe handling of specials, split cours, duplicates and absent provider data.

Use offline fixture suites for new code: different webhook GUIDs/names for same verified anime/episode, genuine alternate episodes, ambiguous mappings, repeat delivery bursts and concurrent claims, cache evidence reuse and cache-poisoning resistance, provider outages, secure path validation, NFO identity, dual-audio, explicit Keep and restart durability. A schema test validates shape and field metadata; component tests validate *evidence authenticity and behavior*.

## Delivery and PR status

- **PR #89:** closed without merge; experimental identity job/hook pipeline superseded.
- **PR #90:** unrelated discovery/backfill design. Do not add automatic Prowlarr backfill in NextGen infrastructure.
- **PR #91:** draft tracing/component-boundary exploration; its previous legacy-assembler/migration-oriented handoff is superseded by **this document**. Reconcile or close obsolete PR directions before merging.
- **PR #92:** draft fresh `ReleaseRecord v1` contract, now requiring exact AniDB episode ID and documentation. **No runtime integration or deployment.**

### Next focused work

1. Review PR #92's schema contract for **exact AniDB anime and episode ID**, verified TVDB episode mapping, owned fields, and serialization/version tests.
2. Build a **fresh NextGen webhook intake** against a **fresh NextGen database**, saving every valid delivery (no GUID/title content dedup), with bounded authentication, logging, trace IDs and load tests.
3. Design identity resolution/cache and post-verification atomic canonical episode claims as separate components before implementing acquisition.
4. Continue NextGen stage-by-stage. Never migrate historical legacy data or connect NextGen to live systems without a separate explicit authorization and rollout plan.

This guide replaces previous mixed legacy-development notes. For host-specific operational setup, inspect the current repository and runtime configuration independently; **do not treat historical text as a deployment instruction**.
