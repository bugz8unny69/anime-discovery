# qBittorrent support and metadata discovery (NextGen)

Minimum supported client: qBittorrent **4.5.0** and Web API **2.8.14**.
qBittorrent 4.2–4.4 and older Web APIs are rejected with `DOWNLOAD_CLIENT_UNSUPPORTED`.

- qBittorrent 4.5, 4.6 and 5.0–5.1: preserve the one-shot, hash-bound
  stopped magnet admission and ownership journal; batch metadata uses export.
- qBittorrent 5.2+ with Web API 2.11.9+: metadata-only fetch where applicable.
- Single-episode pre-manifest discovery checks status every 5 seconds, checks
  the file list periodically while `metaDL`, and stops after a bounded
  24-poll window (about two minutes) before the existing 60-second defer.
  The existing ten-minute overall admission deadline remains unchanged.
- The existing schema-driven Settings → qBittorrent panel now exposes metadata
  poll interval (1–10 seconds, default 5) and checks per window (1–24,
  default 24). Saved changes apply to new operations without a DB migration.
- A per-worker semaphore permits at most two simultaneous single-episode
  metadata polling windows. Different worker processes do not share it.
- On completion, cancellation, or error, the existing stop, ownership,
  cleanup and one-use submission safeguards remain in force.

Do not infer audio availability from the torrent name: `ffprobe` remains
the authority for Japanese/English audio requirements.

Verification: targeted offline tests; no CI runs requested.
