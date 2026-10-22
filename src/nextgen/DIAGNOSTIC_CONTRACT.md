# NextGen diagnostic infrastructure contract — design draft

Status: design prepared after reason registry PR #97 and schema policy PR #99.
This document proposes the implementation boundary. It does not implement
durable writers, a coordinator, journald integration, or supervisor reload.

## Outcome and scope

Every essential delivery/job transition must have bounded, interpretable audit
history committed with its state change. Runtime logs add troubleshooting
detail; they never replace history or determine retry policy.

The implementation belongs in a dedicated diagnostic-infrastructure PR before
coordinator execution. Keep the domain AnimeSeries v2 untouched. No provider,
acquisition, dashboard, management API, or process supervision implementation
is required to prove this foundation.

## Mandatory human-readable messages

Follow [HUMAN_READABLE_MESSAGES.md](HUMAN_READABLE_MESSAGES.md): **every emitted
marker, reason/error, checkpoint and displayed state requires central English
copy and a stable namespaced translation key**. Journal entries include both
codes and resolved sentences; dashboard and CLI use the same catalog.
Registration must cover normal waiting/progress/success as well as errors.
Do not synthesize prose by replacing underscores or interpreting exceptions.

The existing reasons.py English messages/actions are the reason source of
truth. Implement event/state catalogs and the common renderer alongside the
durable diagnostic writers; translation loading can follow later, using the
keys defined by the policy. The initial renderer uses complete static English
sentences and keeps variable facts in separate fields.

## One contract, two destinations

| Fact | Durable SQLite history | Runtime structured log |
| --- | --- | --- |
| What happened | Registered event_code | Same event_code as the event name plus resolved English event message |
| Why, when relevant | Registered reason_code, nullable | Same reason_code and resolved reason message |
| Delivery correlation | event_id FK, directly or through jobs | event_id and derived trace_id when present |
| Independent work | job_id FK | job_id |
| Provenance | jobs.created_by_job_id, nullable | Optional bounded created_by_job_id |
| Attempt and recovery facts | Validated safe_details fields | Validated attempt and contextual decision |
| Emitting component | Proposed component column | component |
| Timing | occurred_at_ms; history_id orders ties | log time, monotonic elapsed_ms when available |
| Troubleshooting | No raw exception or payload | Catch-boundary exception type/traceback under a defined safe-output policy |

Write the durable record in the transaction first. Emit the corresponding
best-effort lifecycle log after commit; rolled-back transitions must not be
logged as completed. A crash between commit and log is acceptable because the
durable history is authoritative. Do not add an outbox solely to guarantee logs.
A logging sink failure after commit must not undo or relabel committed work.
An exception during the transaction rolls back both state and history.
Storage failure itself may only reach runtime diagnostics until recovery.

## Stable initial lifecycle catalog

Scopes and reason requirements are validated by the shared writer.

| event_code | Scope | Reason | Default English message |
| --- | --- | --- | --- |
| ACCEPTED | incoming event | Absent | Incoming event accepted. |
| SERIES_IDENTIFIED | incoming event | Absent | Anime series identification completed. |
| CREATED | job | Absent | Job created. |
| CLAIMED | job | Absent | Job processing started. |
| LEASE_EXPIRED | job | JOB_LEASE_EXPIRED | The processing lease expired before the job completed. |
| RETRY_SCHEDULED | job | Required | Another processing attempt has been scheduled. |
| NEEDS_REVIEW | job | Required | Processing has stopped for review. |
| DONE | job | Absent | Job completed. |

Event message keys are event.<CODE>.message. SERIES_IDENTIFIED does not imply
episode coverage or acquisition. DONE means only this independent job completed;
successor creation, when required, must still be in the same transaction.
LEASE_EXPIRED records the observed expiry during ownership-fenced recovery.

Display states require state.<entity>.<CODE>.label:

| Entity | Code | Default English label |
| --- | --- | --- |
| job, incoming_event | PENDING | Waiting to be processed |
| job, incoming_event | RUNNING | Processing |
| job, incoming_event | RETRY_WAIT | Waiting for another attempt |
| job, incoming_event | NEEDS_REVIEW | Needs review |
| job | DONE | Completed |
| incoming_event | IDENTIFIED | Series identified |

The two entities use separate keys even where English text matches. These
labels cover all states currently permitted by SQLite v3; they add no state.
All reason codes use reasons.py copy and reason.<CODE>.message/action keys.

These are new-emission rules, not a rejection policy for historical reads.
Unknown historical event/reason codes must remain readable using generic copy.
Reject unregistered new event/reason codes at write time.
LEASE_EXPIRED and the resulting RETRY_SCHEDULED or NEEDS_REVIEW can be separate
history rows in one transaction; they do not introduce a new job state.
The coordinator later validates transitions and determines retry eligibility.
The diagnostic writer validates audit shape, not scheduler business policy.
No FAILED/CANCELLED state or event is invented before those semantics are designed.

## Correlation and attempts

- Derive delivery trace_id as AD-<event_id> from the database identity, never
  from provider text, release title, GUID, or user-supplied trace values.
- Jobs without an event use JOB-<job_id>. These labels are stable within one
  NextGen database, not globally unique across separate installations.
- A job associated with a delivery logs both event_id/AD trace and job_id.
  Retries retain job_id and event_id; attempt_count increments only on claim.
- created_by_job_id remains optional provenance. Follow it to explain which
  job requested another job; never infer dependencies or lifecycle propagation.
  A successor's event association must be explicit and validated by its creator.
- CLAIMED and subsequent attempt outcomes record attempt in safe_details.
  CREATED may use attempt=0. For RETRY_SCHEDULED, attempt describes the
  attempt just concluded, not a pre-incremented future claim.
- Retry-exhaustion details retain max_attempts and cause_reason_code; the
  top-level reason is JOB_RETRY_EXHAUSTED.
- Do not store or log lease tokens. The coordinator must still use them in
  conditional state mutations; history insertion does not confer ownership.

## Durable writer boundary

Proposed shared APIs: append_event_history and append_job_history in a new
NextGen diagnostic-history module. Each requires a caller-owned active SQLite
transaction, validates typed and bounded fields before INSERT, and never
commits, opens a connection, changes job state, retries SQL, or logs success.
Reject use outside an active transaction so a history write cannot silently
autocommit separately from its transition.

Required facts: positive signed-64-bit target ID; nonnegative signed-64-bit
occurred_at_ms; known event_code and reason rules; known emitting component;
details rebuilt through safe_details, not json.dumps of arbitrary input.
Unknown detail keys, malformed values and excessive sizes fail with static
validation messages without echoing input. Serialize canonical JSON with
allow_nan=False. Enforce a small encoded-size cap (4 KiB) in addition to
per-field bounds. History writers are internal interfaces, not authorization.

Update accept_event, accept_event_and_job, enqueue_job, and save_identity to
use the common writers while preserving their existing transaction ownership.
enqueue_job must now insert CREATED in the same transaction as its job row;
accept_event_and_job must not duplicate that record. Existing save_identity
idempotent returns must not append duplicate successful transitions.
An intake-created job's emitting component is intake; a job created by a
handler records the actual creator component, not an inferred parent role.
Caller APIs must make component attribution explicit where it is ambiguous.

## SQLite version and compatibility proposal

Durable component attribution cannot be reconstructed reliably from the
existing v3 rows. The implementation therefore needs a **v4 migration**, not
an unversioned addition hidden inside a JSON field.

Add nullable component TEXT to event_history and job_history, constrained to
the same current component vocabulary as settings.py. NULL means historical
origin was not captured; new shared writers require an explicit valid value.
Preserve all existing rows and their unknown reason/event text.
Record attempts using the bounded details fields already introduced by #97.
No new trace column, provenance relationship, or domain field is necessary.

Include 004_diagnostic_components.sql, a matching fresh SCHEMA and user_version
update, all storage query/helper changes, SCHEMA_POLICY.md changes, and
fresh-install plus sequential v1→v2→v3→v4 offline tests in the implementation PR.
Leave 001/002/003 untouched. A version-aware migration runner remains later
work; do not start using scripts against any live database.

## Runtime logging and reload

Extend the existing event helper's correlation allowlist deliberately for
created_by_job_id and use the stable lifecycle event names above.
Do not copy catalog retryable into a retry decision: null means undetermined,
and boolean recovery decisions must reflect actual policy/evidence.
The audit source must not depend on logger.isEnabledFor.

configure_logging currently reapplies levels within a process. Preserve that
capability and validate settings before replacing active configuration.
Supervisor transport, reload signals, generation distribution and acknowledgments
are later work; no reload service or file watcher is claimed here.

Review the current regex redaction against legacy lessons: access_token/apikey
query parameters, x-emby-token, signatures, quoted/space-containing values,
and exception source lines can expose secrets that simple patterns miss.
Do not claim arbitrary exception text is secret-free because a formatter ran.
The implementation must define a bounded safe traceback representation and
ensure configured sinks receive it without exception locals or raw payloads.
Static public reason messages never depend on exception strings.
Journald ingestion is a deployment integration, not a new Python log backend
already present.

## Offline acceptance cases to author, without executing

1. Catalog validation for event scopes, missing/disallowed reasons, unknown
   new codes, valid unknown historical reads, and component validation.
2. Detail type/size boundaries, secret-bearing rejected inputs, static errors,
   deterministic serialization, and absence of raw values in history.
3. Refusal outside a transaction; commit and rollback coupling for delivery,
   initial job+CREATED, identity, and representative job transition writes.
4. Successor insertion plus predecessor DONE and both histories roll back
   together on injected failure. This is a storage contract test, not a worker.
5. Multiple jobs per delivery, jobs without a delivery, retry attempt identity,
   nullable historical component, and optional created_by_job_id preservation.
6. History persists at CRITICAL logging; disabled/failed log sinks do not
   suppress committed history. Rolled-back work has no success lifecycle log.
7. Fresh v4 and sequential upgrades preserve IDs, payloads, foreign keys,
   indexes, histories and versions; failed upgrade does not claim v4.
8. Safe exception diagnostics at every supported level, bounded output and
   no secret leakage across known redaction edge cases.
9. Reapplying validated local logging settings changes verbosity without
   duplicate handlers; invalid settings leave the active logger unchanged.
10. Every event/reason/state has English copy and stable translation keys;
    journal includes codes plus sentences, shared presentation resolves the
    same catalog, unknown history has readable generic text, and missing
    translations fall back to English. See HUMAN_READABLE_MESSAGES.md for
    the complete coverage, safe-rendering and locale acceptance requirements.

Tests must be committed with implementation but remain **unexecuted** under
the current project policy. Do not trigger CI. This design draft contains no
executable test cases and supplies no evidence of runtime correctness.

## Remaining sequence

Implement and review this shared contract with its v4 persistence changes and
offline test cases. Then implement coordinator ownership, routing, retries and
atomic completion against it. Dashboard, supervisor distribution, management
API, intake service and provider business logic remain later milestones.
