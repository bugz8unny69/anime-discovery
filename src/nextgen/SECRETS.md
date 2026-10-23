# Required provider settings and private credentials

AniDB and TVDB are required by the identity worker. There are no provider enable
flags. TVDB authentication uses only an API key; the previous optional PIN model
has been removed from Credentials, configuration and login request construction.
A provider may still reject a key at runtime; that produces PROVIDER_AUTH_FAILED.

## Public configuration

Configuration v4 adds these next-operation fields:

| Field | Default | Readiness requirement |
| --- | --- | --- |
| anidb.client_name | Empty | Registered name, 3–32 allowed characters |
| anidb.client_version | 1 | Integer 1–999999 |
| providers.timeout_seconds | 30 | Integer 1–60 |

Blank client name supports initial setup but cannot pass identity-worker
readiness. Explicit v3→v4 conversion adds defaults and increments revision;
historical v0→v1→v2→v3 outputs retain their original key/default shapes. No
SQLite change is needed (database remains v9; AnimeSeries remains v2).

## Private credential repository

SecretStore(config_directory) manages a separate secrets.json envelope with
schema_version=1, a positive independent revision and a credentials object
containing only tvdb_api_key. An empty key means unconfigured/explicitly cleared.
This is a new NextGen format, not an automatic import of a legacy secret file.
The TVDB key is never accepted in settings.json, jobs, diagnostic history or SQL.

- initialize(tvdb_api_key="") explicitly creates a new file and refuses replacing
  an existing file. Reads never create files. ConfigurationStore.initialize does
  not implicitly create secrets or perform network requests.
- update_tvdb_api_key(value, expected_revision=...) atomically replaces or clears
  the key. Revision conflicts prevent overwrites; unchanged values do not rewrite.
- status() returns only revision and tvdb_api_key_configured. Mutation results
  expose this status plus saved/durability fields; they contain no secret values.
- tvdb_credentials() is a trusted internal provider method returning a Credentials
  object with its API key hidden from repr. Never serialize this object into an
  API response. Public management handlers should use status(), not this method.

The file must be service-owned, regular, single-link and inaccessible to group
or other users. Reads reject symlinks/FIFOs/nonregular files and unsafe modes.
New temporary/final secret files use mode 0600. The parent directory must be
service-owned and not writable by group/others. Installation must establish
these permissions; the library never repairs ownership or changes installed
file permissions to bypass errors.

Publication uses the existing stable settings lock, same-directory temporary
files, file fsync, atomic replace and directory fsync. Failure before replace
preserves the old file. Failure confirming directory durability after replace
reports saved=True/durability_confirmed=False with the existing readable reason;
callers must inspect current status before retrying. No plaintext backup files
are created. Error messages contain no values, paths or raw filesystem errors.
Settings and secret revisions are independent; there is no claim of a two-file
atomic transaction. Management can stage their updates while work is paused.

## Worker composition

await build_identity_worker(config_directory, ...) validates local startup
settings and the TVDB key before constructing the worker. The returned worker is
unstarted and must be served or closed by its owner. run_identity_worker supplies
the worker's existing SIGTERM/SIGINT handling, bounded dispatch and draining.
These are library entry points, not installed systemd services or subprocesses.

The composed worker checks fresh settings/credential availability under
maintenance admission before every claim. Missing/unsafe credentials or an
unconfigured AniDB client raise a static reason-coded configuration error,
leaving queued jobs untouched. The polling loop stops/drains for correction.
Startup/readiness validation does not log in, validate the remote API key or
send any provider request. The identity job later performs both provider checks.

The resolver captures Options and Credentials once per attempt before contacting
providers. Running work keeps those values; later attempts see changes. Up to
four option-specific clients remain cached without mutating in-flight clients;
provider-wide SQLite pacing and public caches remain shared. TVDB memory cache
keys include the API-key fingerprint so rotated credentials do not reuse old
credentials' token/response entries. Old entries expire/evict normally; secret
values and bearer tokens are never persisted or logged.

There is no legacy environment fallback, TVDB PIN, provider disable switch,
authenticated management endpoint, ADM command or supervisor implementation in
this change. Future management routes call these service-side libraries under
the service account with their own authentication/authorization.

Offline cases are authored but unexecuted under project policy. No application
imports/execution, SQL, CI/tests, live provider calls or deployment occurred.
