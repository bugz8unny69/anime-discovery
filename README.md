# Anime Discovery

Private development repository for the Anime Discovery homelab application.

## Status
**Development / migration in progress. Not production-ready.**

The currently deployed application is separate from this repository. No GitHub change automatically modifies the Anime Discovery VM.

## Scope
Autobrr webhook ingestion, canonical anime identity, controller and episode tracking, qBittorrent verification and acquisition, dashboard and authentication, safe staging, rejection enforcement, and administrative CLI.

## Deployment constraints
Application: `/opt/anime-discovery`; configuration: `/etc/anime-discovery`; state: `/var/lib/anime-discovery`. No new systemd unit changes or writes outside these locations without approval. Back up the existing installation and SQLite state before a clean install; stage and verify replacement and preserve rollback.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for progress and [SECURITY.md](SECURITY.md) for repository hygiene.

**Source import pending:** the original uploaded application archive has been located for review but has not yet been imported into this repository. Do not treat this documentation checkpoint as the full application source.
