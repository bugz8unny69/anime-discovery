# Anime Discovery

Private development repository for the Anime Discovery homelab application.

## Status
**Development / migration in progress. Not production-ready.**

The currently deployed application is separate from this repository. No GitHub change automatically modifies the Anime Discovery VM.

## Scope
Autobrr webhook ingestion, canonical anime identity, controller and episode tracking, qBittorrent verification and acquisition, dashboard and authentication, safe staging, rejection enforcement, and administrative CLI.

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
