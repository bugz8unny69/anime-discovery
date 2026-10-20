# AniDB episode ID before acquisition

AniDB's internal episode identifier (`eid`) is distinct from the AniDB anime
identifier (`aid`) and the episode number (`epno`). Anime-Lists provides
`aid`, the TVDB series link, and the numbering conversion; it does not
provide `eid`.

The trial identity worker only authorizes acquisition after a unique
Anime-Lists episode mapping, unique TVDB episode verification and a verified
AniDB `eid` from either an already-reviewed local mapping or a direct AniDB
episode catalog lookup. It never contacts Shoko during pre-acquisition triage.
The `eid` is stored in `verified_anidb_episode_ids` and is used after
the manual Keep action when Sonarr has imported media and Shoko handoff runs.

## Optional authoritative AniDB lookup

AniDB's native HTTP API is **plaintext** and rate-limited. The application does
not contact that plaintext endpoint directly. Use a trusted HTTPS reverse proxy
to the official AniDB HTTP API, with a registered AniDB HTTP client identity,
and set in `settings.json`:

```json
"anidb": {
  "enabled": true,
  "http_api_url": "https://your-trusted-anidb-gateway.example/httpapi",
  "client": "your_registered_client",
  "clientver": 1
}
```

The proxy should enforce appropriate request pacing, caching, and access
control; do not expose a public unrestricted HTTP-API relay. AniDB anime
responses are cached locally for at least 24 hours. Configure the server
and client according to AniDB terms and registered-client requirements.

If these options are missing, the worker can still use manually verified
episode IDs from `identity.episode_map`, otherwise the series stays in
review with `VERIFIED_EPISODE_MAPPING_MISSING`. A missing AniDB episode
in the authoritative catalog never causes the worker to invent an ID.

`shoko.auto_link_verified` continues to default to false. Even when enabled,
the Shoko linking path runs only after Keep, after a verified Sonarr import.
