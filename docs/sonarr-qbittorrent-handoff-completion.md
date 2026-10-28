# Sonarr → qBittorrent handoff: completion checklist

This document is the scope and progress record for **one** follow-up pull request
against `NextGen`. Keep it simple: use existing NextGen workers, jobs, tables,
and adapters. Do not create a separate framework or split this work across PRs.

## Existing implementation (already merged)

PR #168 merged Sonarr ranked-candidate acquisition, magnet admission through
the qBittorrent adapter (including 4.2.x metadata handling), recovery without
duplicate submission, automatic cleanup after terminal candidate failure, and
ranked fallback after cleanup and reservation release.

The existing worker supports `python -m src.nextgen worker --sonarr-acquire`,
and its example systemd unit enables that path. The implementation checkpoint
is `docs/nextgen-sonarr-acquisition-status.md`.

**Implemented does not mean verified.** That checkpoint says its offline
regression tests were written but not executed; it does not establish a
successful end-to-end acquisition.

## Complete in this PR

- [ ] Confirm the deployed worker's `--sonarr-acquire` path uses the existing
  Sonarr discovery, selection, and qBittorrent acquisition registrations.
- [ ] Run the existing **offline** Sonarr → qBittorrent tests; repair actual
  failures, without adding extra architecture.
- [ ] Verify offline that a ranked Sonarr candidate is selected, handed to the
  qBittorrent adapter once, and advanced to acquisition/staging on success.
- [ ] Verify offline failed candidate cleanup and next-ranked fallback; manual
  Cancel must remain final, not trigger fallback.
- [ ] Verify offline qBittorrent 4.2.5 versus newer Web API behavior, including
  paused/stopped magnet admission and metadata polling.
- [ ] Run the relevant NextGen CI checks and fix only failures related to this
  path. Report unrelated failures separately rather than expanding scope.
- [ ] Record exactly what passed, what failed, and any remaining blocker in the
  PR description before requesting merge.

## Out of scope

- No homelab live end-to-end test in this PR, as requested by the operator.
- No unrelated refactoring, new worker/table abstractions, or branch cleanup.
- Do not claim deployment readiness solely from offline test success.

**Goal:** a single reviewable PR showing which Sonarr → qBittorrent handoff
behaviors are implemented and which have actually passed offline tests.
