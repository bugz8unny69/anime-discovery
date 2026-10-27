# Sonarr magnet acquisition: implementation checkpoint

This feature branch is **not ready for deployment or merge**. Issue #167 remains
open in scope; the complete acquisition/failover assignment is not finished.

## Implemented in this checkpoint

- The installed `python -m src.nextgen worker` entry point now accepts
  `--sonarr-acquire`. It enables the existing backfill, source selection,
  and acquisition registrations together. The example NextGen systemd worker
  unit now passes the flag so a deployed worker activates that existing path.
- The 4.2.5 adapter now permits up to 20 one-second metadata polls during
  each owned resume/pause window instead of the former ~2-second window.
  This improves slow metadata discovery but is not live-daemon validation.
- Old-API tagging after a successful add uses one bounded readback routine for
  ordinary and pre-manifest admissions. It rejects another destination, category,
  automatic-management mode, active state, or existing tags.
- `MagnetPermit` is a compatibility alias for the existing one-use `SendPermit`.
- Start/stop endpoints use negotiated Web API capabilities throughout transfer
  and cleanup, rather than the application major version.
- A verified, stable stopped inventory can complete PREPARE_ACQUISITION. The
  completion transaction publishes the acquisition plan and original stopped
  submission receipt together, retaining the original marker and destination.
  SUBMIT_TORRENT then reconciles the original torrent instead of sending again.
- Observed inventory is a distinct evidence type. Migration 46 permits a NULL
  metainfo SHA256 in the existing acquisition table. No metainfo bytes or hashes
  are synthesized. Deserialization checks the explicit evidence discriminator.
- Observed inventories cannot authorize a fresh submission. Promotion requires
  the durable, exact-owned v45 admission and its matching captured inventory.
- Promoted admissions use normal inventory-bounded cancellation cleanup.
  Unpromoted admissions continue to retain reservations and require review.

Published migrations 1–45 remain unchanged. Migration 46 rebuilds the existing
acquisition table and preserves its rows, references, and indexes. There is no
new persistent table or worker service.

## Remaining work

1. Connect definitive candidate failure to ownership-checked cleanup, confirmed
   reservation retirement, and ranked replacement through normal verification.
   `fail_candidate` and `next_candidate` are still disconnected from that flow.
2. Replace the one-choice-per-episode selection constraint with per-attempt
   history and a current selection, without allowing old attempts to reactivate.
3. Finish cancellation/cleanup for admissions lacking a usable inventory.
4. Consolidate the pre-manifest journal with the submission journal, including
   recovery of existing v45 rows. It cannot simply be dropped: those rows may
   represent live torrents or uncertain submissions.
5. Verify the pre-selection metadata window on a live daemon. qBittorrent 4.2.5 requires a
   resume to obtain magnet metadata; a bounded client-side poll/finally-pause
   does not guarantee zero unwanted payload, particularly on process death or
   a network outage. Do not describe it as a metadata-only server operation.
6. Run actual qBittorrent 4.2.5 and newer-daemon integration scenarios, then
   GitHub CI once the whole implementation is complete.

## Verification scope

Offline tests exercise transport responses, one-use permits, inventory evidence,
SQLite migration parity/rollback, and worker completion handoff. They do not
establish live qBittorrent compatibility or complete Sonarr-to-staged-media
behavior. The 4.2.5 source at release commit
`2c65b796401f924d6889aadde958de3d2846bb4b` was inspected: file rows have positional
indexes and piece ranges; add accepts paused/autoTMM but has no inline tags.
This source inspection is not a live daemon test.

The local runtime denies AF_UNIX socket creation, affecting the admin socket
and systemd notification tests. Preserve those tests; do not skip or weaken them.
GitHub CI has deliberately not been triggered while the feature is incomplete.
