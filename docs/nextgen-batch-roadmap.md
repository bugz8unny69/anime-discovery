# Anime Discovery NextGen: batch/OVA delivery roadmap

Updated: 2026-10-26. Target branch: NextGen. Legacy reference: develop.

**This PR implements only the safe batch-planning foundation.** It does not make
season packs downloadable, retryable, stageable or independently verified yet.

## Completed in this feature branch

- [x] **NG-BATCH-00 (foundation scope):** Document boundaries and sequence.
- [x] **NG-BATCH-01 (advisory scope):** Classify release labels as regular single,
  season pack, season+extras, special, ambiguous or unknown. No webhook title is
  trusted as an episode identification or approval.
- [x] **NG-BATCH-02 (read-only inventory):** Parse hash-bound BEP3 multi-video
  torrent inventory as a **BatchInventory**, separate from the production
  single-video **Manifest**. Preserve path, size, hash and payload guards.
- [x] **NG-BATCH-03 (pure planning foundation):** Parse regular episode paths,
  distinguish obvious OVA/specials, reject ambiguous or cross-season videos,
  require unique caller-supplied canonical episode mapping and E01 presence,
  prepare a six-episode E01-first plan without external side effects.
- [x] Offline unit tests for the above Shiki S01 + OVA, season-two numbering,
  unsafe files and duplicate/missing episodes; run in isolation locally with a
  minimal inventory-type stand-in. The full repository test suite and GitHub
  CI were not run at the user's request.

## Outstanding work (not implemented or authorized by this PR)

- [ ] **NG-BATCH-04:** Independently verify the *full* per-file
  AniDB/Anime-Lists/TVDB mapping, including specials, actual AniDB IDs, and
  offset/split-mapping ambiguity. Pass a trusted mapping into the planner.
- [ ] **NG-BATCH-05:** Design durable batch episode-verification facts and
  migrations, with per-file episode ownership and transaction boundaries.
- [ ] **NG-BATCH-06:** Implement provider-confirmed trial/cour/season windows,
  deduplication, size budgets, and explicit partial-pack rules.
- [ ] **NG-BATCH-07:** Wire batch inventory + plan into an owned torrent
  acquisition workflow: paused file manifest confirmation, E01 only selected,
  then unlock E02-E06 *after* durable verified audio proof. Never automatically
  select extras or unknown files. Preserve single-episode code path.
- [ ] **NG-BATCH-08:** Per-file download verification, audio, staging, Keep,
  Reject, cancellation and deduplication—preserve existing ownership gates.
- [ ] **NG-BATCH-09:** Bounded per-episode verification diagnostics for
  VERIFY_RELEASE and batch planner outcomes.
- [ ] **NG-BATCH-10:** Show distinct identity vs. episode/batch evidence in
  dashboard; allow an operator to see selected/skipped file reasoning.
- [ ] **NG-BATCH-11:** Supported safe RETRY/requeue lifecycle, **owned by another
  chat/PR**. Avoid conflicting queue/schema updates here.
- [ ] **NG-BATCH-12:** Full unit, SQLite, worker and mocked-torrent integration
  tests including mixed OVA, duplicated releases and crash/restart recovery.
- [ ] **NG-BATCH-13:** Full CI and upgrade acceptance only when explicitly
  requested; verify production install and no regression to single episodes.

## Critical design boundaries

1. Classification from the release title is a **hint only**.
2. BatchInventory has **no selected_index**, so it cannot substitute for
   Manifest in current acquisition APIs.
3. BatchSelection is an **untrusted plan**, not durable provider evidence,
   authorization, proof of download or an ownership marker. Do not persist,
   execute or expose its output as verified without the next tasks.
4. Filenames marked OVA or special are merely excluded from a prospective
   regular-episode plan; no future code may use a loose keyword to authorize
   deletion or bypass per-file verification.
5. Never auto-transition existing NEEDS_REVIEW rows or add RETRY behavior here.
6. Existing IDENTIFY_ANIME / VERIFY_RELEASE / PREPARE_ACQUISITION job routes
   intentionally remain single-episode until batch contracts are added.

## Acceptance target

A Shiki "S01 + OVA" torrent with separately identified E01-E12 files and OVA
extras should verify all regular episodes against provider truth, select E01
first, unlock only E02-E06 after a durable JP+EN audio proof, and never acquire
OVA files or E07+ by accident. Unknown episode numbering must require review.
