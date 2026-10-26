# Anime Discovery NextGen — Batch/OVA implementation tracker

Updated: 2026-10-26. Target branch: NextGen.
Reference: legacy batch-selection design on develop.
Work tracked in draft PR #149. Separate review retry infrastructure: draft PR #150.

**This draft branch implements batch parsing, provider verification, policy
planning and durable schema primitives. No worker or endpoint is wired to
execute them yet. DO NOT DEPLOY until the remaining pipeline and migration
checks pass.**

## Implemented in PR #149 (not merged)

- [x] **NG-BATCH-00:** Document boundaries, dependency order and handoff.
- [x] **NG-BATCH-01:** Advisory single-episode, season-pack, season+OVA,
  special and ambiguous-title classification; title is never authority.
- [x] **NG-BATCH-02:** Hash-verified, bounded multi-video BEP3
  BatchInventory; existing Manifest still strictly single-video.
- [x] **NG-BATCH-03:** Pure filename parser and E01-first legacy-style
  selection with explicit episode mappings, fail-closed unknowns,
  duplicates, wrong season, ambiguous multi-episode files and extras.
- [x] **NG-BATCH-04 (provider primitive):** Validate every regular video
  against the AniDB episode catalog, Anime-Lists forward/reverse mapping and
  unique TVDB episode records, including offsets and season-two naming.
  Fails closed on missing/conflicting evidence and validates torrent identity
  before planning. Not yet wired into VERIFY_RELEASE.
- [x] **NG-BATCH-05 (storage primitive):** Add schema v27
  batch_verifications / batch_verified_files; migrate v26 -> v27;
  provide immutable per-file proof persistence under a fenced worker lease.
  No worker completion handler or downstream reservation consumes these yet.
- [x] **NG-BATCH-06 (pure policy primitive):** Intersect full verified
  batch episode evidence with current Window(backfill_count,
  following_count), including anchors beyond the initial episodes.
  No durable window budget/reservation or torrent selection authorization yet.

## Remaining integration and verification

- [ ] Wire NG-BATCH-04 into VERIFY_RELEASE and add typed batch completion
  alongside the existing single-episode pathway. Preserve single releases.
- [ ] Wire NG-BATCH-05 persistence into the worker's fenced completion
  transaction, then expose a separately typed source for trial evaluation.
- [ ] Finish NG-BATCH-06 with durable trial/window commitments, episode
  reservation arbitration, size budgets and explicit partial-pack handling.
- [ ] **NG-BATCH-07:** Owned torrent submission, stopped/stable manifest
  reconciliation and per-file selection: download probe first; unlock remaining
  only after independently verified durable JP+EN audio proof.
- [ ] **NG-BATCH-08:** Per-file download verification, stage, Keep/Reject,
  cancellation, ownership-safe cleanup and duplicate staging behavior.
- [ ] **NG-BATCH-09:** Explain mapping and file-exclusion reasons in bounded,
  durable VERIFY_RELEASE/batch evidence.
- [ ] **NG-BATCH-10:** Dashboard episode coverage and selected/skipped file
  diagnostics, distinct from anime identity matching.
- [ ] **NG-BATCH-11:** Explicit review retry endpoint/worker handoff,
  separately owned in PR #150 / another chat. Do not duplicate that code.
- [ ] **NG-BATCH-12:** Offline full integration tests with fake AniDB, TVDB,
  qBittorrent, worker crash/restart and SQLite transactional proof.
- [ ] **NG-BATCH-13:** Full repository CI and upgrade/migration acceptance
  after user explicitly permits running them; production deployment.

## Safety invariants

- An incoming release title and torrent filenames are *hints*, not proof.
- BatchInventory contains no selected_index and cannot satisfy the existing
  single-video Manifest acquisition contract.
- Provider-confirmed per-file identities are required before trial selection.
- The v27 proof tables are additive and **not** a download permit.
- The new proof writer requires an active fenced VERIFY_RELEASE job claim,
  event/torrent hash alignment and all regular video files to be accounted for.
- Unknown/ambiguous files and mixed seasons fail closed. A known OVA filename
  is only skipped for planning, not automatically deleted.
- Configured trial windows are read-only input; no worker queue, metainfo
  source, qBittorrent, staging or Sonarr workflow changed in this draft.
- Existing NEEDS_REVIEW rows remain untouched.

## Acceptance target

Shiki S01 + OVA: identify the anime, hash-verify torrent file inventory,
provider-verify each distinct regular episode, mark OVAs as skipped, record
durable per-file evidence, select the allowed first probe, prove JP+EN audio,
then download and stage remaining authorized episodes without selecting OVAs
or E07+ by accident (unless configured trial policy expressly includes them).

## Testing state

New focused regression tests were committed. GitHub CI was not started or
checked, and full repository tests were not run, per user request.
The assistant's current runtime cannot access the private repository
checkout to execute tests locally. Do not treat this as a tested/merge-ready PR.
