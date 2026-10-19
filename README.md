# Anime Discovery

Private development repository for the Anime Discovery homelab application.

## Status
**Development / migration in progress. Not production-ready.**

The currently deployed application is separate from this repository. No GitHub change automatically modifies the Anime Discovery VM.

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
  "qbittorrent": {"base_url": "http://127.0.0.1:8080", "username": "admin", "cleanup_source": true}
}
```

Example `secrets.json`:

```json
{"web_token": "choose-a-private-token", "qbittorrent_password": "your-qb-password"}
```

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

POST `/webhook` with the shared bearer token. Required fields are
`release_name`, `source_guid`, and `info_hash`. If the payload **also**
includes `tvdb_id`, `anidb_id`, `season`, `episode`, and
`magnet_uri`, the webhook immediately binds that supplied episode identity,
records approval, and queues the acquisition. Otherwise the notification
appears in the inbox for browser approval. Repeated notifications with the same
source and GUID are deduplicated. Repeated episode approvals do not create
additional jobs. Rejected series cannot be approved until reset.

These IDs must be trustworthy metadata supplied by your integration;
the webhook does not independently resolve release names through AniDB/TVDB.

The dashboard includes Reject, Reset, and Clear History controls. Reject
blocks acquisition; Reset makes a series eligible again; Clear History
currently clears the initial-search completion marker, not all historical
notification or acquisition records.

To install the optional system service, copy `deploy/anime-discovery.service`
to `/etc/systemd/system/`, adapt its account and repository paths to your VM,
then run `systemctl daemon-reload` and
`systemctl enable --now anime-discovery`.

## Offline fresh-install smoke check

From the repository root with Python 3.12:

```bash
export PYTHONPATH=src/legacy
python src/legacy/anime-discovery-admin.py --db /tmp/anime-discovery-smoke.db new-database
python src/legacy/anime-discovery-admin.py --db /tmp/anime-discovery-smoke.db doctor
python -m unittest -v test_anime_fresh_acquisition_integration test_anime_admin_cli
```

Choose a new database path; `new-database` intentionally refuses to overwrite an
existing file. `doctor` is read-only and exits nonzero for an incomplete database.
These commands do not start services, enable acquisition, or contact qBittorrent.
They are a database smoke check, **not** proof that the complete dashboard,
webhook server, installer, or deployment is ready.

## Deployment constraints
Application: `/opt/anime-discovery`; configuration: `/etc/anime-discovery`; state: `/var/lib/anime-discovery`. No new systemd unit changes or writes outside these locations without approval. Back up the existing installation and SQLite state before a clean install; stage and verify replacement and preserve rollback.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for progress and [SECURITY.md](SECURITY.md) for repository hygiene.

**Source import pending:** the original uploaded application archive has been located for review but has not yet been imported into this repository. Do not treat this documentation checkpoint as the full application source.
