# AniDB episode IDs: official HTTP API and local SQLite catalog

Anime-Lists supplies an AniDB anime ID and rules to translate AniDB episode
numbers into TVDB seasons and episodes. It does **not** contain AniDB's internal
episode record ID (eid). Before trial acquisition, Anime Discovery verifies
the Anime-Lists / TVDB result and retrieves eid from an AniDB anime episode
catalog, independently of Shoko.

## Configuration

Register an **HTTP API client** through AniDB's client registration process.
Provide the registered client identifier and its version in
`/etc/anime-discovery/settings.json`, within your existing `anidb` section:

```json
"anidb": {
  "enabled": true,
  "client": "your_registered_client_name",
  "clientver": 1
}
```

The `http_api_url` key from older builds is no longer necessary. **Remove any
HTTPS gateway URL** from this setting. If retained for compatibility, it must
be blank or equal to `http://api.anidb.net:9001/httpapi`.

The official read-only HTTP API endpoint is:

```text
http://api.anidb.net:9001/httpapi
```

For `request=anime`, the application submits `aid`, `client`,
`clientver`, and `protover=1`. No AniDB username or password is submitted.
**HTTP is unencrypted:** client identifiers, request metadata and response
contents can be read or altered in transit. Client registration is still
required, and rate-limit violations can affect the client or source IP. Do
not treat plaintext responses as cryptographically authenticated.

## Storage and request pacing

Metadata is stored in a separate indexed SQLite file alongside the daemon
state database:

```text
/var/lib/anime-discovery/anime-discovery.db   # jobs, approval, Keep, per-notification proof
/var/lib/anime-discovery/anime-metadata.db    # fetched AniDB anime and episode catalog
```

If the operational DB lives elsewhere, `anime-metadata.db` is created in the
same directory as the configured `daemon.database_path`.

The cache contains:
- `anidb_anime_catalog`: AniDB anime ID, last successful fetch, episode count
- `anidb_episode_catalog`: AniDB anime ID, regular episode number, exact eid
- `anidb_http_rate_limit`: shared next request time across worker processes

For a new anime, **one API request fetches the full episode catalog**. Known
positive episode IDs are served locally without another upstream request.
An absent episode number is rechecked no more than once per 24 hours per
anime. Upstream requests are spaced by at least 10 seconds across processes,
with an additional 10-minute cooldown following a failed/invalid API response.
Pending cooldowns defer worker identification without marking it as reviewed.

The `settings.json` file stays small; episode catalogs do not belong there.
The main operational DB retains only the verified internal episode ID linked to
an individual notification so Shoko can use that exact evidence after Keep.

## Existing data and fallback behavior

The previous `anidb-episode-cache/anime-<aid>.xml` files are not loaded by
the new SQLite catalog. They can be removed separately after validation; do
not delete or move the application state database.

A missing or invalid client name prevents new AniDB HTTP lookups. Already
reviewed `identity.episode_map` entries continue to work. If AniDB does not
yet include an episode or a mapping is ambiguous, no episode ID is invented.
The release remains in review after normal lookup retries.

Shoko is never queried for pre-acquisition episode identity. **Only when
you click Keep** does Sonarr import trial media into the permanent library.
The post-Keep Shoko monitor then reuses the persisted episode ID to help
recover an unrecognized file. `shoko.auto_link_verified` remains disabled
unless explicitly enabled by the user.
