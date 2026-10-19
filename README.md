# Anime Discovery

Private development repository for the Anime Discovery homelab application.

## Status
**Development / migration in progress. Not production-ready.**

The currently deployed application is separate from this repository. No GitHub change automatically modifies the Anime Discovery VM.

## Scope
Autobrr webhook ingestion, canonical anime identity, controller and episode tracking, qBittorrent verification and acquisition, dashboard and authentication, safe staging, rejection enforcement, and administrative CLI.

## One-command live homelab launch

Run this from the repository root on the machine with access to qBittorrent
and your mounted download/trial folders. Use Python 3.12. The first command
is needed **once** for a fresh database; do not rerun it on an existing DB.

```bash
export PYTHONPATH=src/legacy
mkdir -p /var/lib/anime-discovery
python src/legacy/anime-discovery-admin.py new-database
export ANIME_WEB_TOKEN='choose-a-private-token'
export ANIME_QB_USER='your-qb-user'
export ANIME_QB_PASSWORD='your-qb-password'
python src/legacy/anime-discovery-live.py \\
  --qb-url http://127.0.0.1:8080 \\
  --download-root /path/to/qb-downloads \\
  --trial-root /path/to/anime-trial
```

If `/var/lib/anime-discovery/anime-discovery.db` already exists, skip
`new-database`. Replace the qBittorrent URL and both paths. Open
`http://HOMELAB-IP:8765/`; browser username is `anime`, password is
`ANIME_WEB_TOKEN`. Autobrr should POST JSON to `/webhook` with
`Authorization: Bearer YOUR_TOKEN`. This launches both processes and
stops them together on Ctrl+C. No systemd installation is required.

## Run the homelab dashboard and Autobrr inbox

Start with an existing unified database (use `new-database` for a fresh install).
From the repository root:

```bash
export PYTHONPATH=src/legacy
python src/legacy/anime-discovery-web.py \\
  --db /var/lib/anime-discovery/anime-discovery.db \\
  --host 0.0.0.0 --port 8765 --token 'replace-with-your-own-token'
```

Open `http://YOUR-HOMELAB-IP:8765/` and log in with username `anime`
and the configured token as password. The dashboard lists series and recent
notifications, and its approval form binds a notification to TVDB/AniDB IDs,
season/episode, and a magnet link, then queues the acquisition job.

Configure Autobrr's webhook POST URL as
`http://YOUR-HOMELAB-IP:8765/webhook` and send
`Authorization: Bearer YOUR_TOKEN`. Send JSON or form fields:
`release_name`, `source_guid`, `info_hash` (40- or 64-character hex);
`source` is optional. Incoming releases are saved to the inbox. Approval
is a separate action on the dashboard.

Run `anime-discovery-worker.py` (below) in a separate terminal to
process approved jobs and submit to qBittorrent. Both processes use the
same database. Keep this service on a trusted homelab network or behind
your existing HTTPS reverse proxy; its browser login uses HTTP Basic auth.

## Run the acquisition worker

The worker processes approved acquisition jobs from the unified database, logs
in to qBittorrent, and stages verified completed media. It runs in the
foreground and can be stopped with Ctrl+C.

```bash
export PYTHONPATH=src/legacy
export ANIME_QB_USER='your-qb-username'
export ANIME_QB_PASSWORD='your-qb-password'
python src/legacy/anime-discovery-worker.py \\
  --db /var/lib/anime-discovery/anime-discovery.db \\
  --qb-url http://127.0.0.1:8080 \\
  --download-root /path/to/qb-downloads \\
  --trial-root /path/to/anime-trial
```

Replace the URL and paths with the actual homelab values. The worker
actively submits approved magnets to qBittorrent; it does not create approvals,
run the webhook/dashboard, or delete original downloads. The database must
already exist. This command is not automatically installed or started by GitHub.

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
