# KEEP_MEDIA — Sonarr copy import (NextGen draft)

Status: **implemented in draft, untested, not deployed**. Keep is scoped to the
selected, already-published staging operation and its exact one verified episode.
Shoko is optional and not involved in the Sonarr import.

## Contract

1. The authenticated Keep action commits one management control job and one
   immutable `keep_imports` approval in the **same SQLite transaction**. The
   approval captures staging manifest and publication receipts, source SHA-256
   and file identity, AniDB identity, exact verified TVDB series/season/episode
   and TVDB episode ID. A synthetic `STAGED` marker without a publication is
   not sufficient. Repeated clicks return the same job and decision.
2. A claimed `KEEP_MEDIA` worker re-hashes the original staged video through a
   no-symlink path and checks the recorded inode, size, timestamps and digest.
   A missing or changed file stops for review; staging remains intact.
3. For the verified TVDB series, Sonarr v3 registration is reconciled by ID.
   An existing series with a different registered root or quality profile is
   **not edited**. Missing series are looked up by TVDB and added with the
   selected quality profile, anime series type, monitoring enabled and **no
   automatic historical missing-episode search**.
4. Exact TVDB-backed season/episode numbers are resolved against Sonarr's
   canonical episode records. A registered existing episode file blocks
   automatic overwrite. Manual-import candidates must match the exact staged
   path; explicit series and canonical episode IDs are supplied in Sonarr's
   manual-import reprocess step. Rejected/ambiguous candidates stop for review.
5. The exact selected import request is durably committed as `IMPORT_INTENT`
   **before** sending `ManualImport` with `importMode=copy`. A lost response,
   crash or timeout at this boundary leaves `IMPORT_INTENT` and does not submit
   another command automatically. Sonarr command receipts are recorded in
   `COMMAND_ACCEPTED`.
6. A recorded command ID must report `completed`; the worker must then observe
   Sonarr's exact canonical episode-to-episode-file link and hash the actual
   permanent file under the approved library root. Content must equal the
   staged evidence and must not be the same inode. Only then may the lease-fenced
   worker commit `VERIFIED` and the Keep job's `DONE` outcome atomically.

## Setup for an isolated lab validation (do not deploy until validated)

- Upgrade NextGen configuration explicitly from v7 to v8; configure
  `sonarr.base_url`, `sonarr.root_folder`,
  `sonarr.quality_profile_name`, `sonarr.timeout_seconds`, and
  `storage.keep_root`. The Sonarr root and Keep root must agree. The endpoint
  is an HTTP(S) origin with no subpath, proxy or embedded credentials.
- Replace the Sonarr API key through the authenticated management settings
  dashboard or `PATCH /api/v1/credentials/sonarr` with `expected_revision`
  and `api_key`. This upgrades the private secrets format to v4 without
  revealing the saved key.
- Under the application's existing exclusive maintenance/backup procedure,
  upgrade the **NextGen-only** SQLite database from v21 to v22. Do not touch
  legacy database files, skip version checks, or run upgrades against running
  services.
- The worker and Sonarr must both see staged files at the **same absolute
  paths** as in the approval. The worker must also read the permanent library
  path that Sonarr reports, with POSIX/NFS permissions sufficient to hash it.
  Use dedicated authenticated, cross-VLAN OPNsense rules. No chmod/chown or
  automatic NFS repair is attempted.

## Recovery boundaries

- `APPROVED`: no remote write. Configure Sonarr and resume the existing job.
- `SERIES_INTENT`: Sonarr series admission may have happened; inspect exact
  TVDB series state before manual retry. No blind duplicate POST.
- `SERIES_READY`: no file import command submitted; re-preview may proceed.
- `IMPORT_INTENT`: import POST may have happened; **manual reconciliation
  required**, no automatic resubmission or generic button retry.
- `COMMAND_ACCEPTED`: resume the recorded Sonarr command/status/digest proof
  without another import. Failed/mismatched copies need operator review.
- `VERIFIED`: the exact permanent copy was proven. No repeat import.

No staging-file deletion, torrent removal, Sonarr rename trigger, Jellyfin
refresh or Shoko handoff happens in this draft. Those follow-up jobs must not
invalidate a completed import. The source remains available for recovery.

## Validation status

Offline tests have been **authored but not executed** for approval and action
deduplication, exact TVDB mapping, copy proof, lost command response, wrong
destination digest, secrets v4, configuration v8 and SQLite v22. No CI, live
Sonarr/Jellyfin calls, filesystem moves, browser tests, migrations, merge or
deployment have been run in this work.


## Follow-up refresh handoff (draft)

After this job completes successfully, a separately owned `REFRESH_JELLYFIN`
job is atomically enqueued if `jellyfin.base_url` was configured at completion.
It requests a library scan only; media success and cleanup never depend on
Jellyfin availability. See [REFRESH_JELLYFIN](REFRESH_JELLYFIN.md).
