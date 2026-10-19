# Integration rollout checkpoint (development only)

This branch is **not approved for VM deployment**. It retains the current `develop` runtime and adds a draft Keep → Sonarr handoff for isolated testing. No installed database or source files are altered by the GitHub commits.

## Configuration

Use `settings migrate` to preview newly supported JSON sections before explicitly applying. Never paste production secrets into GitHub.

- `sonarr.enabled` (default false), `base_url`, `root_folder`, `quality_profile_id`; place `sonarr_api_key` in mode-0600 `secrets.json`.
- `tvdb.enabled` (default false), `base_url` (defaults to the TVDB v4 endpoint); place `tvdb_api_key` in `secrets.json`. When enabled, Keep verifies its TVDB ID read-only before Sonarr admission.
- `ntfy.enabled` (default false), HTTPS `server`, `topic`, HTTPS `dashboard_url`, `reminder_hours`; optional `ntfy_token` in `secrets.json`. Newly received unmatched webhooks produce best-effort notifications; recurring reminders are not yet connected to the unified database.
- `shoko.enabled` (default false), `base_url`, `auto_link_verified`, `poll_seconds`; optional `shoko_api_key` is supported by existing settings. No Shoko episode link writes should be enabled until a pinned API contract and exact file/episode identity are verified.
- `jellyfin.enabled` (default false), `base_url`; `jellyfin_api_key` remains in `secrets.json`.

## Keep semantics in this branch

A Keep click requires verified trial media and a TVDB ID. It verifies the configured Sonarr Anime profile and `/mnt/media/Anime` root using the live Sonarr API, then adds or finds the series by TVDB ID. It requests Sonarr ManualImport with `importMode=copy` after verifying each exact staged file maps to one Sonarr episode. The resulting command ID and import manifest are persisted as `SONARR_IMPORT_PENDING`.

A separate monitor polls the command. Once completed, it verifies that Sonarr's imported episode files exist under the configured root and have identical SHA256 hashes to staged media. It then checks that no other release uses the same torrent hash and, if the original torrent still exists, its save path lies in the configured download root, not the trial or Sonarr root. Before `deleteFiles=true`, every video file inside the torrent must hash-match a staged imported item; this blocks partial multi-episode pack deletion. Only after those checks may the original torrent and trial media be deleted and the series marked `KEPT`.

The original torrent is **not** automatically reassigned to Sonarr by adding a series. Deleting an old torrent is distinct from Sonarr managing future acquisitions through its own download-client setup. Existing qB cleanup after staging may mean the old torrent is already absent; that is handled as an idempotent no-op. API/schema behavior and network mount permissions are still subject to VM acceptance.

Shoko file/episode linkage remains read-only and fail-closed until the 5.3.3.0 API contract is pinned and tested against the internal Swagger specification.

## Acceptance gates

1. Mock-client and API tests pass on the feature branch, then review/merge the PR into `develop`.
2. Confirm the deployed configuration and API permissions on each host without printing secret values.
3. Simulate duplicate, unmatched, rejected, and approved webhooks; verify notification behavior.
4. Verify NFS trial file visibility, Jellyfin refresh, Sonarr creation on Keep, and Shoko's passive metadata behavior.
5. Only after integrated results are accepted, produce a new archive from `develop`. Do not merge into `main` or deploy as part of this draft.

## Confirmed homelab integration targets (2026-10-19)

- Sonarr hostname `sonarr.arr.internal`; configure an explicit HTTP(S) URL with an appropriate, verifiable certificate.
- Sonarr root folder as seen by Sonarr: `/mnt/media/Anime`.
- Sonarr quality profile display name: `Anime`; numeric profile ID must be discovered from the server before enabling.
- Shoko Server: 5.3.3.0; internal Swagger UI at `https://shoko.arr.internal/swagger/`. API schema inaccessible from this execution environment; no Shoko write action approved.

**Requested KEEP policy:** Import existing staged trial episodes into Sonarr's permanent root. User also wants original trial files and the original Anime Discovery torrent payload removed. **This is now implemented behind the confirmation monitor, but has not been tested against the real VM.** The monitor deletes original data only after Sonarr file and torrent payload verification. Before cleanup, independently verify actual Sonarr episode-file records, on-disk destination files, and torrent ownership. Adding a series in Sonarr does not automatically transfer management of an existing qBittorrent torrent. Never delete that torrent on the assumption Sonarr adopted it; coordinate the torrent client and ownership handoff explicitly. Leave NFS data unchanged on timeout, unclear ownership, ambiguous episode mapping, or partial import.

**Important:** Sonarr's root folder and trial folder must be distinct. Confirm the exact trial root and ensure both services resolve the same staged file path for Manual Import. This is a deployment prerequisite, not an assumed path mapping.
