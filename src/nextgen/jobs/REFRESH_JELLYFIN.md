# Jellyfin refresh after Stage and verified Keep — NextGen

**Status:** unmerged draft. No tests, CI, live HTTP requests, Jellyfin
scans, database upgrades or deployment executed.

## Behavior

Jellyfin scanning is an **independent follow-up**, never part of staging or
Sonarr's import verification:

- Successful `STAGE_TRIAL_MEDIA` persists its published manifest and STAGED
  operation state; when Jellyfin is configured, that same worker completion
  atomically enqueues a `REFRESH_JELLYFIN` job in a **new operation**.
- Successful `KEEP_MEDIA` first persists verified Sonarr library file proof;
  the same completion transaction then schedules an independent Jellyfin
  refresh, if enabled. A failed/uncertain Keep imports **nothing** into this
  follow-up and never initiates a Jellyfin scan.
- The refresh worker checks its `created_by_job_id` and original event/job
  identity against a committed `PUBLISHED` staging publication or `VERIFIED`
  Keep journal before making the request. Arbitrary client-supplied job kinds
  or source paths cannot trigger a scan.
- The worker sends `POST /Library/Refresh` with a modern
  `Authorization: MediaBrowser Token="..."` header. The private key never
  appears in query strings, logs, SQLite, receipts or status views. Requests
  have bounded timeouts, no ambient HTTP proxy, and no redirects.
- A successful HTTP response means **scan accepted**, not a completed scan
  or proof Jellyfin has indexed the file. A failed request retries its own
  job; after retry exhaustion the refresh job needs review. It never
  rolls back staging, Keep, Sonarr registration or permanent files.

This initial integration requests a **global library scan**, intentionally
covering a newly created staging series/episode even before Jellyfin has
assigned item IDs. The library must already contain the mounted staging
and/or Sonarr permanent paths. A later optimization may target configured
library IDs rather than scanning every library after each episode.

## Configuration

- **Settings schema v9**: `jellyfin.base_url` (empty disables automatic
  refresh) and `jellyfin.timeout_seconds` (default 15). The origin must
  be HTTP(S), with no embedded credentials, query, fragment or subpath.
  Use HTTPS via a trusted endpoint whenever crossing VLANs.
- **Secrets schema v5**: `jellyfin_api_key`, saved in the private service-owned
  secrets file. Set through the authenticated dashboard or with
  `PATCH /api/v1/credentials/jellyfin` using `expected_revision` and
  `api_key`. Only a configured/not-configured flag is returned.
- Configure Jellyfin with libraries pointing to the same files that NextGen
  stages and Sonarr imports. Jellyfin requires filesystem/NFS visibility of
  those paths; a scan request cannot compensate for an inaccessible mount.
- Explicitly migrate existing configuration from v8 to v9 before running
  this branch. The **SQLite version remains v22**; no new DDL is required
  for independent job receipts. Earlier config/secret/SQLite migrations from
  previous draft PRs still apply to a lab system that has not installed them.

Setting Jellyfin's URL to empty suppresses new refresh jobs; an already
queued refresh remains durable and may need manual review if the endpoint
is later cleared. Jobs are not retroactively created for older DONE stage
and Keep operations.

## Unrun tests and outstanding work

Offline tests cover acceptance versus HTTP failure, token privacy, stage
successor enqueuing in a fresh operation, scan failures not rolling back media,
disabled behavior, and the Keep successor contract. Tests were authored
but **not run** per current project policy. Browser checks, live Jellyfin
index confirmation, credentials validation against the deployed server and
lab deployment still need authorized execution.

Optional Shoko remains separately queued work and is never a Sonarr
prerequisite. The configured missing-episode search window, safe
post-Keep cleanup, supervision and full integration validation remain open.
