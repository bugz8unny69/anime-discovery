# qBittorrent metadata retrieval (NextGen)

The former `torrent_metadata.base_url` and `torrent_metadata.timeout_seconds`
settings are obsolete. No separate HTTP(S) server or tracker is required.
Configuration schema v12 removes them; a versioned v11→v12 migration checks
the complete old settings document and drops only that unused section.

NextGen's source of metadata is now the configured qBittorrent client:

- On Web API 2.11.9+ (qBittorrent 5.2+), `fetchMetadata` and `saveMetadata`
  can return a portable, infohash-verified `.torrent` inventory without ever
  adding a torrent. The qB adapter can parse either a strict single video
  (`Manifest`) or a multi-video batch (`BatchInventory`).
- On older Web APIs with `torrents/export` (2.8.14+), NextGen can inspect
  and export portable BEP3 bytes from an *already stopped* torrent. Export
  and source inspection are read-only; they are not ownership evidence.
- On Web APIs without export, qBittorrent's `torrents/files` is only an
  observed file list, not portable cryptographic BEP3 metadata. The existing
  legacy single-episode bootstrap has a one-shot, journaled stopped magnet
  admission for these clients. It must not be repurposed for batch
  `VERIFY_RELEASE` without its own durable preverification journal,
  recovery, downstream adoption and cleanup rules.

Batch verification still requires individually verified AniDB episodes,
Anime-Lists mapping and TVDB episode IDs, and must not add/overwrite an
unrelated torrent. No batch can download until the separately journaled
submission and controlled file selection succeed.

> **Known gap:** older clients cannot complete first-time season-pack
> metadata discovery with the current verifier. A safe owned-stopped batch
> observation path, compatible with the full batch lifecycle, remains
> necessary. This gap must not be hidden by claiming `torrents/files`
> exposes the original `.torrent` or by synthesizing `info_sha256`.
