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
{"web_token": "choose-a-private-token", "qbittorrent_password": "your-qb-password"}
```

**First installation:** check out the repository under /opt/anime-discovery,
then run `sudo python3 deploy/install-homelab.py`. The zero-flag installer
prompts for existing directories and qBittorrent credentials, writes settings
and secrets with restricted permissions, creates a fresh database if missing,
and enables the systemd service. It does not replace existing configuration.

Create the configuration directory and keep `secrets.json` readable only
by its owner (`chmod 600 /etc/anime-discovery/secrets.json`).
Initialize a fresh database once using the admin CLI, then start:

```bash
python src/legacy/anime-discovery-live.py
```

The launcher starts the dashboard/webhook and acquisition worker together.
Open `http://HOMELAB-IP:8765/` with username `anime` and password
`web_token`. Autobrr POSTs to `/webhook` using
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
