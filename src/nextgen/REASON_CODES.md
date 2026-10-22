# NextGen operational reason-code registry (draft)

The machine-readable catalog lives in `src/nextgen/reasons.py`. It is an initial
NextGen definition informed by legacy diagnostic/tracing concepts (PRs #67 and
#91); it is **not** a verified copy of a complete legacy error-code catalog.
The old catalog was not conclusively located.

## Contract

- `event_code` in `job_history`/`event_history` says **what happened**
  (examples: `CREATED`, `CLAIMED`, `RETRY_SCHEDULED`, `DONE`,
  `NEEDS_REVIEW`); `reason_code` explains **why**, when needed.
- `reason_code` is a stable, uppercase identifier and should remain
  interpretable for historical rows after UI text is updated. Do not recycle
  an existing code to mean something else.
- The coordinator decides job state, whether and when to retry, and writes
  state and audit rows in **one transaction**. Catalog `retryable` is only
  a recommendation/classification, **not** an automatic retry instruction.
  `NEEDS_REVIEW` is not necessarily a software error.
- `details_json` stores only small, allowlisted, non-secret facts; never
  request bodies, provider payloads, raw exception text, credentials, or
  personally sensitive data. `safe_details` currently supports verified
  field names and an optional retry timestamp; add typed schemas deliberately
  as coordinator events are implemented.
- `display_reason` gives the future dashboard and `m` command the same
  human-facing message and action. They must handle unknown historical codes
  gracefully and may display extra technical detail only in an advanced view.
- `journald` debug/trace verbosity is separate from durable job/event
  history; essential timeline information persists at every log level.
- This proposal introduces no SQLite tables, new services, coordinator loop,
  UI or authentication. Unknown codes must not prevent reading existing
  history. New emitted codes should be registered and documented.

## Initial reason codes

| Code | Meaning in dashboard |
| --- | --- |
| `IDENTITY_INCOMPLETE` | Anime identification is incomplete. |
| `IDENTITY_INVALID` | Anime identification could not be verified. |
| `IDENTITY_CONFLICT` | Conflicting anime information needs review. |
| `PROVIDER_UNAVAILABLE` | An information provider is temporarily unavailable. |
| `JOB_LEASE_EXPIRED` | Processing was interrupted. |
| `JOB_HANDLER_FAILED` | An unexpected processing error occurred. |
| `JOB_RETRY_EXHAUSTED` | Automatic retries have stopped. |
| `STORAGE_UNAVAILABLE` | Processing is temporarily unavailable. |
| `UNSUPPORTED_JOB_KIND` | This type of work cannot be processed. |

Severity and suggested action are specified in the code registry. These
are **proposed categories**, not claims of already implemented coordinator
behavior. Later, evaluate each code against the actual handler outcome and
refine action/retry guidance without exposing technical internals.

## Example

A job writes `event_code=RETRY_SCHEDULED`,
`reason_code=IDENTITY_INCOMPLETE`, and
`details_json={"missing_fields":["anime.title"],"retry_at_ms":1234}`
in the same SQLite transaction as its retry state transition.
The dashboard might show: *Anime identification is incomplete; the system
will retry*. The actual retry time comes from the job row, not catalog text.

## Testing and release

Offline tests cover registry consistency, unknown-code display and safe
details. They are committed for later local execution. CI remains disabled.
Do not merge/deploy without explicit authorization.
