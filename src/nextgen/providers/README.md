# AniDB-first identity libraries

This library supplies a concrete resolver for the opt-in identify_anime_job.
It adapts the legacy title parser, AniDB catalog/compression/exact episode checks,
SQLite request reservation/cooldown, TVDB response/token caching and explicit
mapping/cross-check behavior. It imports no legacy runtime code.

## Composition and current input

Service composition supplies validated `Options(client_name, client_version)`
and a thread-safe `credentials()` callback returning `Credentials(api_key, pin)`
from its secret facility. No credentials are put in public settings or payloads.
`make_resolver(options, credentials)` returns the async callable consumed by
`identify_anime_job.registration(resolve, release_kind=...)`. Share that resolver
across the worker's attempts so its TVDB token/cache survive normal job deferrals.
The optional release kind must already be installed. No release handler is added.

Options are constructor policy, not newly accepted settings.json keys. Timeout is
bounded to 1–60 seconds (default 30); registered AniDB client name/version are
required. Service bootstrap, secret-storage UI/API and provider configuration
schema/management fields remain to be implemented together, with explicit
conversion when those settings are registered. This PR does not install a
standalone service or enable provider requests automatically.

The initial default normalizer requires a JSON body containing release_name.
It does not claim compatibility with every producer's webhook. A future intake
adapter can normalize supported producers or supply a trusted title_extractor.
Duplicate JSON keys, invalid JSON and missing names fail closed. Body size remains
bounded by the identity job. Filename episode/season hints never prove identity.

## Verification order

1. Extract bounded title aliases, using the adapted legacy parser. Query the
   cached official AniDB title dump first. Require one exact normalized anime
   candidate; multiple/no candidates go to review, without guessing from TVDB.
2. Fetch/reuse the ID-specific AniDB HTTP anime record. Validate response anime
   ID, a main title and consistency with the title index.
3. Read the cached Anime-Lists mapping. Require exactly one mapping row with a
   positive TVDB ID for that AniDB anime.
4. Authenticate to TVDB and fetch the exact extended series. Validate ID, explicit
   animation genre, no conflicting live-action classification, corroborating
   AniDB titles and no contradictory explicitly labeled AniDB remote link.
5. Return AnimeSeries v2 with verified series facts and zero release episodes.
   The release job must establish exact episode coverage before acquisition.

A title overlap alone is insufficient; success requires independently fetched
AniDB identity, explicit mapping, and ID-specific TVDB checks. Ambiguity, missing
metadata or conflict yields review. Multiple AniDB anime may legitimately share
one TVDB series ID; the resolver does not merge them or impose whole-anime locks.
The legacy title parser strips season labels for candidate discovery; explicit
S02/Season 2-or-later hints currently go to review rather than accidentally
approving the first entry. Part/season disambiguation and broader matching are
future release/identity evidence work, not guessed here.

## Caching and throttling

| Source | Cache | Request admission | Failure behavior |
| --- | --- | --- | --- |
| AniDB anime HTTP | Validated full-anime XML in SQLite, 24 hours; regular episode IDs reuse the same response | Shared SQLite reservation, at least 10 seconds apart | Shared 10-minute error cooldown; honors longer Retry-After |
| AniDB title dump | Public XML in SQLite, 24 hours | A shared reservation prevents another download within 24 hours, including after a failed attempt | Fail closed; preserve the daily reservation |
| Anime-Lists mapping | Public XML in SQLite, 24 hours | Shared one-minute download spacing | Bounded shared cooldown |
| TVDB | Process-local authorization-scoped series cache, 15 minutes; tokens 30 minutes | Shared SQLite one-second spacing, including login | Honor bounded Retry-After and shared backoff; a rejected bearer token is discarded |

These are conservative application policies adapted from legacy, not a claim
that they coordinate other applications using the same public IP. All local
workers sharing the NextGen database share reservation/cooldown state. No thread
sleeps while holding a job slot for rate pacing: ProviderDeferred returns to the
job, which requests DEFERRED/RETRY_WAIT. For example, cold TVDB login reserves a
request, caches the token in memory and defers its GET until the next allowance;
the next job attempt reuses the token. Actual HTTP work is bounded and offloaded;
forced cancellation waits for the owning thread before releasing admission.

Cache hits precede upstream reservation. Public XML is revalidated on reuse;
invalid responses never replace good entries. Newer reservation generations
prevent late responses overwriting newer cache data. Clock rollback does not make
future-fetched cache entries usable. Public cache is bounded to 130 rows/128 MiB.
TVDB memory cache is a thread-safe 128-entry LRU, with detached results and keys
scoped by credential fingerprint; credentials/tokens are never persisted.
The regular episode helper validates exact positive AniDB epno/eid ownership,
rejects duplicate IDs/numbers and does not invent specials or TVDB numbering.
A missing regular episode remains missing until the anime cache refreshes.

## HTTP, diagnostics and storage

Endpoints are fixed in code. Redirects are rejected, particularly for authenticated
TVDB calls. Responses and decompressed bytes are bounded. Gzip/deflate handling
and AniDB regular-episode validation adapt the legacy implementation; unknown
content encoding, DTD/entity XML, wrong IDs, duplicate/nonfinite JSON and malformed
records fail closed. The legacy AniDB metadata endpoint is plain HTTP; only
public metadata and registered client identifiers are sent there, never TVDB
credentials or user account credentials. Network authenticity limitations of
that endpoint are not solved by schema validation.

ProviderDeferred maps to JOB_WAITING without spending failure retry budget.
ProviderUnavailable and ProviderInvalidResponse produce reason-coded retries;
authentication/authorization failure produces review with PROVIDER_AUTH_FAILED.
Storage failures retain the infrastructure-error path. No HTTP response body,
URL, credentials, token or exception text is logged or saved in diagnostic history.
Existing catalog messages/actions are reused and new reasons are translation-ready.

Schema v9 adds provider_limits and provider_public_cache. The versioned 009
migration, fresh schema, runner/version guards and offline cases accompany these
helpers. No runtime CREATE TABLE, implicit migration or legacy metadata import.
Provider operations require the caller's job admission; HTTP occurs outside
SQLite transactions. Configuration remains v3 and AnimeSeries remains v2.

This draft has not contacted providers, run SQL, executed/imported application
code, run tests/CI or changed media/production. Tests are authored but unexecuted.
Integration/operational confidence is deferred under current project policy.
