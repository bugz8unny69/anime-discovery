# NextGen operational reason-code registry

The machine-readable catalog lives in `src/nextgen/reasons.py`. It is a fresh
NextGen definition informed by legacy diagnostics and identity-triage behavior,
not a port of a complete legacy catalog. No runtime dependency on legacy exists.

## Contract

- `event_code` says **what happened**; `reason_code` explains **why**, when
  needed. Neither is the incoming delivery's `event_id`.
- New emitted reasons must be registered. Codes are stable uppercase ASCII
  identifiers, at most 64 characters; never recycle a code's meaning.
- `retryable` is advisory: true means a potentially transient condition,
  false means repeating unchanged work is not the suggested remedy, and null
  means the code alone cannot classify recovery. It never grants retry
  permission, determines a state, sets a delay, or overrides attempt limits.
  The worker and handler outcome decide recovery using actual evidence.
- Severity describes a condition, not the job state or process health.
  `NEEDS_REVIEW` can represent a normal per-item outcome.
- `display_reason` supplies static plain-language messages and actions.
  Unknown historical identifiers get generic text and null retryability.
  Malformed, non-string, or oversized identifiers display as `UNKNOWN`.
  Never pass secrets as codes: syntactic validation cannot detect a secret
  that happens to resemble an identifier. Render all values as text in a UI.
- `safe_details` builds small JSON-compatible facts before persistence.
  It rejects unknown arguments and invalid values; it is not a scrubber for
  arbitrary payloads. Never provide raw requests, provider responses, names,
  URLs, paths, tokens, lease tokens, exception strings, or credentials.
- Logging filters must never suppress essential SQLite lifecycle history.
  State changes and their history belong in the same transaction. A failed
  storage write cannot reliably record its own failure in that same database;
  sanitized runtime logging is the fallback, with later reconciliation.

## Catalog and recovery classification

| Code | Dashboard message | Retry classification |
| --- | --- | --- |
| `IDENTITY_INCOMPLETE` | Anime identification is incomplete. | Context required |
| `IDENTITY_INVALID` | Anime identification could not be verified. | Changed input/evidence needed |
| `IDENTITY_CONFLICT` | Conflicting anime information needs review. | Review needed |
| `PROVIDER_UNAVAILABLE` | An information provider is temporarily unavailable. | Potentially transient |
| `JOB_LEASE_EXPIRED` | Processing was interrupted. | Potentially transient |
| `JOB_HANDLER_FAILED` | An unexpected processing error occurred. | Context required |
| `JOB_RETRY_EXHAUSTED` | Automatic retries have stopped. | Review needed |
| `STORAGE_UNAVAILABLE` | Processing is temporarily unavailable. | Context required |
| `UNSUPPORTED_JOB_KIND` | This type of work cannot be processed. | Component change needed |

Lease expiry does not prove a handler had no external effects. Recovery must
fence stale owners and establish whether replay is safe. A handler exception
may be deterministic; a storage error may be locking, disk exhaustion,
corruption or an uncertain commit. Do not classify all these as automatic retries.
Unsupported work must remain visible; do not silently discard it.

## Comparison with the current foundations

SQLite v6 retains arbitrary historical reason text in `last_reason_code`, `event_history`
and `job_history`; no SQL enum or schema migration is needed for this catalog.
Job states are PENDING, RUNNING, RETRY_WAIT, NEEDS_REVIEW and DONE; event states
also include IDENTIFIED rather than DONE. States are not reason codes.
Storage emits ACCEPTED, CREATED and SERIES_IDENTIFIED through the shared
history writers. messages.py registers the remaining lifecycle codes for
worker integration, plus runtime-only OPERATION_FAILED. The worker
execution loop itself remains unimplemented.

`IDENTITY_CONFLICT` covers canonical TVDB disagreement, conflicting retry
results and an episode already owned by another AniDB anime. Two AniDB anime
sharing a TVDB series is allowed and is not, by itself, a conflict.
`IDENTITY_INVALID` covers failed candidate validation; `IDENTITY_INCOMPLETE`
covers missing verification evidence. Numeric shape validation alone is not
provider verification. A valid series-only AnimeSeries v2 with zero episodes
does not trigger either reason. Missing optional placement is not a series
identity failure; future handlers enforce their own operation prerequisites.

Older prose in `development.md` calls these INCOMPLETE_IDENTITY and
INVALID_IDENTITY. Those were descriptive draft names, not aliases emitted by
this registry; new code uses IDENTITY_INCOMPLETE and IDENTITY_INVALID.
Historical unknown identifiers remain readable with generic display text.

The merged diagnostics helper accepts `reason_code` and a boolean
`retryable` log field. A null catalog classification must be omitted there.
The logging field should describe a contextual decision, not blindly copy a
catalog hint. The PR #100 diagnostic infrastructure implements correlation, durable history
writers, event-code validation and shared English/translation-key rendering.
See DIAGNOSTIC_CONTRACT.md and HUMAN_READABLE_MESSAGES.md.

Legacy diagnostics contribute bounded correlation, catch-boundary exceptions
and redaction lessons. Legacy exact episode/TVDB placement gates do not become
new mandatory AnimeSeries v2 fields. No acquisition or provider-specific reason
catalog is invented before those components are designed.

## Structured details

| Field | Allowed values |
| --- | --- |
| `missing_fields`, `invalid_fields` | Up to 20 schema-location names from the explicit allowlist; sorted and deduplicated |
| `retry_at_ms` | Optional nonnegative signed-64-bit integer timestamp |
| `attempt`, `max_attempts` | Optional nonnegative signed-64-bit integer observations |
| `cause_reason_code` | Optional registered reason, e.g. the last cause when retries stop |

Booleans are not integers here. Omitted values produce no field; empty detail
is an empty object. Field values and arbitrary nested attributes are never
accepted. Lists name schema locations without exposing their values.
Only report episode fields for relevant supplied entries or an operation
requiring episode evidence, never because a valid series has no episodes.
These fields explain a condition; canonical scheduling still lives in the
job row. The helper does not enforce worker transition policy.

Example: a policy-authorized retry may record
`event_code=RETRY_SCHEDULED`, `reason_code=PROVIDER_UNAVAILABLE`,
`details_json={"attempt":2,"max_attempts":3,"retry_at_ms":1234}`.
Whether a retry is actually scheduled comes from persisted state, not the
message text. Exhaustion can retain PROVIDER_UNAVAILABLE as cause_reason_code.

## Delivery and validation status

This PR supplies the reason catalog, presentation helper and detail builder,
with offline tests authored but **not executed** under the current project
policy. The reason catalog itself required no SQL change; diagnostic PR #100 adds
SQLite v4 component attribution. No CI runs, worker execution, dashboard,
management API, journald integration or supervisor reload distribution are
included. Existing Python logging/settings and central reason copy are reused.


The v5 schema adds held/blocked/canceled lifecycle states and typed activity
without deriving status from a reason string. See JOB_STATUSES.md.

## Configuration-library reasons and markers

| Code | Human-readable meaning |
| --- | --- |
| CONFIGURATION_INVALID | Configuration could not be validated. |
| CONFIGURATION_CONFLICT | Configuration changed before this update could be applied. |
| CONFIGURATION_MIGRATION_REQUIRED | Configuration needs an upgrade. |
| CONFIGURATION_STORAGE_FAILED | Configuration storage is unavailable. |
| CONFIGURATION_DURABILITY_UNCONFIRMED | Configuration was updated, but durable storage could not be confirmed. |

The first three require corrected input, refreshed revision or explicit upgrade,
not an automatic unchanged retry. Storage outcomes require context; successful
rename plus failed directory sync does not mean nothing saved. See
CONFIGURATION.md. CONFIGURATION_SAVED, CONFIGURATION_MIGRATED and
CONFIGURATION_SAVE_UNCONFIRMED are runtime-only event markers in messages.py.
Every reason/message/action retains the same stable translation-key contract.
These additions do not alter SQLite schemas or diagnostic-history detail shapes.


### Maintenance and database upgrades

The shared libraries add MAINTENANCE_PENDING, MAINTENANCE_BUSY,
MAINTENANCE_FAILED, DATABASE_VERSION_UNSUPPORTED, DATABASE_SCHEMA_INVALID,
DATABASE_MIGRATION_CONFLICT and DATABASE_MIGRATION_FAILED. Every entry has a
static English message/action and translation keys. Retry hints do not schedule
retries or clear maintenance. The future API catches typed errors and emits
OPERATION_FAILED with their reason_code, never raw SQLite messages/SQL/paths.

Runtime success markers DATABASE_MIGRATED, MAINTENANCE_REQUESTED and
MAINTENANCE_COMPLETED resolve the same shared catalog. They do not add job states
or incoming-event history rows. Durable marker/schema state drives recovery
independently of logging; a management audit API/table remains future work.
See storage/MIGRATIONS.md for drain, backup and partial-upgrade behavior.
