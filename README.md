# Anime Discovery

Private development repository for the Anime Discovery homelab application.

## Status
**Homelab dashboard, installer, Autobrr intake and acquisition daemon; VM installation not yet verified.**

GitHub commits do not automatically deploy to the Anime Discovery VM.

## Scope
Autobrr webhook ingestion, canonical anime identity, controller and episode tracking, qBittorrent verification and acquisition, dashboard and authentication, safe staging, rejection enforcement, and administrative CLI.

## Live homelab runtime (configuration only)

All three entrypoints read `/etc/anime-discovery/settings.json` and
`/etc/anime-discovery/secrets.json`. There are no runtime flags or
environment-variable credentials.

Example `settings.json`:

```json
{
  "daemon": {"database_path": "/var/lib/anime-discovery/anime-discovery.db", "concurrency": 4, "lease_seconds": 300},
  "web": {"host": "0.0.0.0", "port": 8765},
  "storage": {"download_root": "/path/to/qb-downloads", "trial_root": "/path/to/anime-trial"},
  "qbittorrent": {"base_url": "http://127.0.0.1:8080", "username": "admin", "cleanup_source": true},
  "identity": {"series_map": {"Example Show": {"tvdb_id": 123, "anidb_id": 456, "season": 1}}}
}
```

Example `secrets.json`:

```json
{"web_token": "choose-a-webhook-token", "admin_password": "choose-a-different-dashboard-password", "qbittorrent_password": "your-qb-password"}
```

**First deployment (new VM code, existing JSON configuration is supported):**

Clone the private repository onto the VM as the intended service account:

```bash
git clone --branch develop git@github.com:bugz8unny69/anime-discovery.git /opt/anime-discovery
cd /opt/anime-discovery
sudo python3 deploy/install-homelab.py
```

The interactive installer detects whether
`/etc/anime-discovery/settings.json` **and**
`/etc/anime-discovery/secrets.json` already exist.

- With **existing JSON files**, the installer previews missing settings,
  asks permission to merge the defaults with a backup, and **never replaces
  existing values or rewrites secrets**. It validates configured storage,
  credentials and ownership before creating a brand-new database at the
  `daemon.database_path` value already in settings.json. If an abandoned
  database exists there, remove or archive it **yourself** before installing;
  the installer refuses to overwrite it.
- With **no JSON files**, the installer prompts for storage and qBittorrent
  settings, writes new JSON files, initializes a fresh database and installs
  the systemd service. A partial configuration is refused.

The service account must own the existing mode-0600 `secrets.json` and
have access to the configuration, media and database paths. The installer
refuses to change ownership of existing secret files silently.
A pre-existing systemd service is also refused, to avoid disrupting another
deployment. After first installation, use
`anime-discovery-admin.py upgrade` for subsequent releases.


The launcher starts the dashboard/webhook and acquisition worker together.
Open `http://HOMELAB-IP:8765/` with username `anime` and the separate
`admin_password`. Autobrr POSTs to `/webhook` using
`Authorization: Bearer YOUR_WEB_TOKEN` and fields `release_name`,
`source_guid`, `info_hash`. The dashboard can approve a notification
and queue its acquisition. `qbittorrent.cleanup_source=true` enables
removing the torrent and downloaded files after staging succeeds.

### Autobrr automatic handoff

POST to `/webhook` with the bearer token. The service accepts
`release_name` or `torrentName`, plus `info_hash` or `torrentHash`.
The source GUID and magnet URI are optional; the torrent hash is used
as the GUID fallback and a magnet is generated from it.

Episodes enqueue automatically with explicit TVDB/AniDB and season/episode
values **or** via the dashboard's **Recognized anime names** mappings.
Configured aliases recognize `S01E02` and `[Group] Example Show - 02`.
Unmatched releases remain in the inbox for manual approval.

Series inspection displays dispatch, job and staged media records.
Reject blocks work, Clear History hides earlier recognized inbox events
without lifting rejection, and Reset lifts the block for new webhooks.
If configured, successful staging/finalization removes both the torrent and
its downloaded source files from qBittorrent.

## Migrating existing VM configuration

If `/etc/anime-discovery/settings.json` and `secrets.json` already exist,
**use the installer’s existing-configuration adoption path**; it preserves both files.
The new admin command merges missing supported defaults into the existing
`settings.json`, preserving the current database path, download/trial paths,
qBittorrent URL, user preferences, and credentials.

Review the proposed additions first:

```bash
sudo python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py settings migrate
```

Then explicitly apply the changes:

```bash
sudo python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py settings migrate --apply
```

The command creates a dated `settings.json.before-migrate-*.bak` backup
containing the **exact original bytes** before replacing `settings.json`.
It never rewrites `secrets.json`; Prowlarr remains disabled by default.
Existing values always win over defaults. Unknown legacy keys or incompatible
values stop the migration and require review rather than being erased.
No SQLite records, torrent data, or service configuration are changed by
`settings migrate`.

To enable the *optional* new Prowlarr integration after migrating, configure
`prowlarr.base_url`, add `prowlarr_api_key` to the existing secrets file
without removing any existing keys, and set `prowlarr.enabled` to true.
Keep `secrets.json` readable only by its owner (mode 0600).

## Fresh-build configuration and credential repair

The fresh installer asks for separate dashboard and webhook credentials and
can configure the working optional Prowlarr one-time discovery integration.
Dashboard Basic authentication (user `anime`) uses `admin_password` only.
Autobrr `POST /webhook` uses `web_token` as its Bearer token only;
neither credential authorizes the other route type.

If you already installed the fresh build, **do not delete your new SQLite database**.
After deploying a release containing this change, run:

```bash
sudo python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py settings configure-credentials
sudo systemctl restart anime-discovery.service
```

Leave the webhook prompt blank to keep your Autobrr token. Enter a distinct
dashboard password when prompted. The command rewrites only `secrets.json`,
preserving existing keys and file ownership. The service refuses to start
without a separate admin password. To configure Prowlarr on an existing
installation, use `settings set prowlarr.base_url` and
`settings set prowlarr.enabled true`, and provision `prowlarr_api_key`
securely in `secrets.json` (0600), then restart the service.

**Integration status:** Prowlarr search is implemented. Jellyfin currently
supports writing trial NFO files, not API-based Jellyfin synchronization.
ntfy notifications and TVDB API lookups are not implemented in this fresh
runtime; entering their URLs or keys would not enable those services.
The installer intentionally does not solicit unused credentials.

## Release archive deployment (no Git clone)

GitHub Actions builds versioned tar.gz and zip releases when changes are
merged into develop. Each release includes SHA256SUMS.

This is a **private repository**: release assets require authenticated
download. Anonymous wget will not work. Download with your authenticated
GitHub browser session or GitHub CLI, then transfer the archive to the VM
using an available secure transport. No Git clone or SSH access is needed
on the VM.

Extract the archive into /opt (it contains an anime-discovery/ directory):

```bash
sudo tar -xzf anime-discovery-build-VERSION.tar.gz -C /opt
cd /opt/anime-discovery
sudo python3 deploy/install-homelab.py
```

Verify the package with the published SHA256SUMS before extraction. The
installer asks for the existing Linux service account (default
anime-discovery) and requires membership in the media group (GID 1002).
It detects existing settings.json and secrets.json, requests confirmation
before correcting permissions, and does not overwrite credentials.
The configured existing database must be archived or removed separately
before installation.

**Archive-based upgrades:** Download and verify the newer release
`.tar.gz`, copy it onto the VM, then run:

```bash
sudo python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py upgrade /path/to/new-release.tar.gz
```

The offline upgrade validates archive entries, makes an online SQLite
backup, stops the service, swaps the application code, starts the service,
and restores the old code if startup fails. The old code directory and
database backup remain available. It does not overwrite
`/etc/anime-discovery`, your NFS mounts, or the SQLite database.
For Git checkouts, `admin upgrade` without a package path still uses Git.

## Built-in VM upgrade and administration

After the first installation, update the checked-out `develop` release and
restart Anime Discovery directly on the VM:

```bash
cd /opt/anime-discovery
sudo python3 src/legacy/anime-discovery-admin.py upgrade
```

The upgrade fetches `origin/develop`, requires a clean checkout and a
fast-forward release, creates an online-safe dated SQLite backup,
stops the service, updates the Git checkout, verifies the database,
and restarts the service. If the service restart fails, the previous Git
revision is restored; the SQLite backup remains available. Git fetches run
as the checkout's owner so the existing private-repository credentials work
when the admin command is launched with sudo.

The admin interface now follows a consistent, discoverable hierarchy:

```text
anime-discovery-admin.py status
anime-discovery-admin.py upgrade
anime-discovery-admin.py database init
anime-discovery-admin.py database doctor
anime-discovery-admin.py settings show
anime-discovery-admin.py settings set KEY VALUE
```

Existing `doctor` and `new-database` spellings still work for older scripts.
The application itself still reads its settings and secrets from flat files;
no environment variables or worker flags are required.

## Dashboard: Series and Jobs

The dashboard has separate tabs for **Series**, **Jobs**, and
**Recognized names**.

**Series** is the Anime-Trial library: an anime appears there only after
an acquisition has completed and at least one staged episode remains on disk.
Simply receiving a webhook or recognizing the anime does not add it to this
view. Series rows show staged episode count, last staged episode and
management status. Select any visible rows with checkboxes, then apply
Reject, Clear History or Reset as one database transaction. List pages
support 20, 50 or 100 rows; selection is confined to the current page.

**Jobs** shows all received Autobrr releases, including unmatched releases,
queued acquisitions and completed episodes. States include Received,
Queued, Running, Waiting for Download, Completed, Blocked and Needs Review.
The open Jobs tab refreshes automatically every five seconds, showing
new notifications and status changes without a manual page reload.
Manual episode approval for unmatched jobs remains accessible here.

**Recognized names** holds the configured TVDB/AniDB title aliases
used to match incoming releases, whether or not they have reached
Anime-Trial. This prevents the library from being confused with the
inbox or the identity configuration.

## Shared Prowlarr episode discovery

Add this section to `/etc/anime-discovery/settings.json`:

```json
"prowlarr": {
  "enabled": true,
  "base_url": "http://YOUR-PROWLARR-HOST:9696"
}
```

Add `"prowlarr_api_key": "YOUR_KEY"` to
`/etc/anime-discovery/secrets.json` (file mode 0600) and restart the service.
Do not put the API key into settings.json, environment variables or flags.

Incoming **Autobrr** episode notifications still enqueue their own verified
release immediately. They also trigger a bounded, one-time Prowlarr search
for earlier episodes, skipping items already acquired or queued.

The **Request Anime** action on the Series page launches a manual **one-time**
Prowlarr search. Enter a known anime name or TVDB/AniDB ID, optionally select
an anime season, and submit. No episode selection and no monitoring of future
releases. The name or ID must already have an unambiguous mapping under
Recognized names. Manual and Autobrr search results pass into the same
verified acquisition and qBittorrent/Anime-Trial staging workflow and
appear in the Jobs page.

Current Prowlarr integration processes magnet-backed, explicitly numbered
episode results with matching title aliases. Torrent download URLs and
anime-title/provider lookup without a recognized mapping are not supported.
Ambiguous releases are skipped rather than guessed.

## Offline fresh-install smoke check

From the repository root with Python 3.12:

```bash
cd src/legacy
python3 anime-discovery-admin.py --db /tmp/anime-discovery-smoke.db new-database
python3 anime-discovery-admin.py --db /tmp/anime-discovery-smoke.db doctor
python3 -m unittest -v test_anime_fresh_acquisition_integration test_anime_webhook_lifecycle test_anime_web_http test_anime_live_acquisition
```

Choose a new database path; `new-database` intentionally refuses to overwrite an
existing file. `doctor` is read-only and exits nonzero for an incomplete database.
These commands do not start services, enable acquisition, or contact qBittorrent.
They are a database smoke check, **not** proof that the complete dashboard,
webhook server, installer, or deployment is ready.

## Filesystem layout
Application: `/opt/anime-discovery`; configuration: `/etc/anime-discovery`; state: `/var/lib/anime-discovery`. The installer installs the systemd unit on the homelab host.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for progress and [SECURITY.md](SECURITY.md) for repository hygiene.

The web service and acquisition daemon are in `src/legacy`; migration-era components may still contain functionality not connected to this live application.
