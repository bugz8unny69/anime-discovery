# Hash-addressed torrent metadata source

The composed identity worker now installs preparation, stopped submission and
download monitoring by default, using a real HTTP(S) metadata reader. Trusted
custom async readers remain supported. Startup performs no metadata fetch or
download-client request; generic workers still need explicit registrations.

Configure `torrent_metadata.base_url` in Settings to a trusted source serving
`<lowercase-v1-infohash>.torrent` under that folder. The placeholder base
`https://cache.example/torrents` yields
`https://cache.example/torrents/<hash>.torrent`. No third-party source is selected
by default. This is not a DHT/magnet resolver, indexer search or authenticated
cache client. A compatible source must actually provide the requested metainfo.

This follows NextGen's metadata-first design. Legacy `qb_trial_add_adapter.py`
vets and adds a magnet before the client learns its file list. NextGen inspects
exact metainfo, inventory, selected-byte budget and episode declaration before
the separate submission journal can authorize a stopped add. Retrieval creates
no temporary download-client entry and proves no torrent ownership.

## Network and validation boundaries

- Only validated operation configuration chooses a base address. Delivery data
  supplies a normalized v1 hash, never a URL, host, path, credential or template.
  Simple ASCII base-folder segments are permitted; traversal, percent encoding,
  user information, query tokens and fragments are rejected.
- HTTP(S) is supported for operator-authorized destinations. HTTPS uses normal
  certificate verification. Redirects and ambient proxy variables are disabled.
- Identity-encoded bodies are capped at four MiB even without Content-Length.
  Invalid lengths, compressed/malformed bytes, wrong hashes and unsupported
  inventories enter review. Preparation independently revalidates metadata and
  checks the filename declaration against verified episode evidence.
- The timeout is 1–60 seconds, default 30. It controls connection/socket reads
  and deadline checks between read1 chunks. It is not an interruptible DNS
  deadline; a socket read may finish after the between-chunk deadline. Cancellation
  is checked before requests and between chunks, and blocking work is drained
  before maintenance/operation protection is released.
- 404/429/503 defer with TORRENT_METADATA_WAITING. Numeric Retry-After is bounded
  to one second through one day; otherwise use 60 seconds. Normal waiting does
  not consume failure retries. There is one request per attempt, without fallback
  origins or automatic HTTP retries.
- Network/read failures and supported transient responses use the worker's bounded
  retry policy with TORRENT_METADATA_UNAVAILABLE. Missing configuration or access
  denial enters readable review. Unsupported replies, including redirects, require
  metadata review. Cancel remains available.

Raw metainfo, tracker URLs and passkeys are not persisted or logged. Before a first
submission intent, submission refetches metainfo and requires the exact prepared
hash-bound manifest. Existing uncertain submission intents reconcile without
another metadata fetch or send permit. Source-setting changes affect new attempts
but cannot bypass exact manifest checks or retarget saved download-client options.

## Configuration and completion boundary

Configuration v7 explicitly upgrades v6, preserving all values and adding a blank
source/default timeout. v0–v6 conversion outputs retain their historical shapes
and reject the new section. Use the existing explicit preview/backup/migration
contract; startup never upgrades settings silently. SQLite remains v18; secrets v3.

Without a configured source, selected work reaches PREPARE_ACQUISITION and
NEEDS_REVIEW with TORRENT_METADATA_CONFIGURATION_INVALID, instead of silently
ending at a completed reservation. A compatible configured source extends the
existing preparation → stopped submission → selected download flow. Video/audio
verification and staging are still next; a completed transfer is not a verified
staged video and does not authorize Keep.

Offline cases cover fixed requests, strict source validation, hash/size/encoding
checks, status outcomes, cancellation/deadline closure, explicit upgrades and
historical shapes, snapshot behavior and preparation handoff. Tests and CI remain
unexecuted. No live sources/clients, migrations, media operations or deployment.
