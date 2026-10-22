# Async worker core

Implemented core only: worker.py, job_contracts.py and storage/job_queue.py.
There are no identity, download, trial, Keep or provider handlers bundled.
The separate management API/supervisor remain future consumers; the worker has
no HTTP server and does not launch subprocesses. The default empty handler
registry fails readiness before claiming work. No worker has been run or deployed.

## Trusted registration and operation

Install explicit Registration entries in Registry. Each binds a stable kind to
a HandlerDefinition (code/static label), callable, async/thread mode, allowed
successor kinds and optional pure route/synchronous persistence adapters. All
allowed successor kinds must be installed. No directory scanning, payload module
names, hooks or arbitrary dynamic imports. Handler modules use `_job.py` names.

The service/application entry point is `await run_worker(config_directory,
registrations)`, which reads current validated startup configuration and handles
SIGTERM/SIGINT by stopping claims and draining admitted work. Startup concurrency
and database location stay pinned; each attempt reads a fresh immutable operation
snapshot. Trial/Keep destinations are available through that snapshot but a
publishing handler must validate configuration, real paths/access and recorded
artifact bindings before acting. The worker itself never moves or deletes media.

A handler receives Context with immutable claim/config references, safe logger,
thread-safe cancellation event and data() returning detached payload data. It
returns an Outcome: complete, retry, defer, hold, review or blocked. Completed
values are feature-specific typed facts for its trusted persistence adapter,
not raw exception strings or generic fields inserted into diagnostic history.

Outcome reasons must be registered. retry/defer delays are bounded; worker policy
sets lease/poll intervals and retry/backoff limits. These policies are validated
constructor parameters, not silently invented settings-schema keys. Registration
requires async functions for async mode, synchronous callables for thread mode.
Do not spawn untracked background threads/tasks from a handler.

## Claiming, invocation and atomic handoff

The async loop bounds active attempts by startup worker.concurrency, checks
expired leases, and claims only due PENDING/RETRY_WAIT rows ordered by readiness
and ID. Each claim uses BEGIN IMMEDIATE, increments attempt_count, sets a fresh
lease token/expiry and writes CLAIMED in one transaction. There is no blanket
per-anime lock or deduplication of incoming deliveries.

Maintenance admission covers configuration read, claim, handler, heartbeat and
final persistence, including offloaded work. Pending maintenance blocks new
admissions while existing work drains. Idle polling does not retain admission.
Provider/resource gates still belong in feature libraries.

Before invoking a known handler, the worker validates bounded object payloads
and commits HANDLER_STARTED. Unknown kinds/invalid payloads go to NEEDS_REVIEW
with readable reason codes without pretending the handler was called. The
heartbeat renews only an unexpired matching RUNNING token/attempt. Failure to
confirm ownership cancels the handler and never assumes it may commit success.

Completion uses a dedicated connection and worker-owned transaction: verify
lease/state/attempt; append handler ending; run the trusted persistence and
routing adapters; insert permitted successors with existing event/provenance;
recheck lease; update job state/release lease and append its audit; commit. All
facts/successors/ending records roll back together on failure. Adapter commit,
rollback and savepoint transaction escapes are denied by SQLite authorization;
adapters must still be short, synchronous database operations with no external
calls or DDL. Route adapters are pure and return at most 32 Successor records.
The worker returns/logs successor CREATED receipts only after the same commit.

Persisted completion is not reconstructed by repeatedly scanning all DONE jobs.
A stale or repeated completion fails ownership checks, preventing a second
successor handoff. No work_items table, parent/child workflow engine, new jobs
columns or SQLite migration is needed for these operations; schema remains v8.

## Waiting, retries and failures

A normal defer (for example a prerequisite/download wait) writes DEFERRED,
RETRY_WAIT and a future availability, with optional permitted activity label.
It does not spend the failure retry budget. attempt_count counts actual claims;
the budget separately counts committed RETRY_SCHEDULED records for this job.

Failure retries use bounded exponential backoff and a registered reason. A
requested retry delay can extend the backoff up to the outcome's one-day bound.
After max_retries committed retry schedules, another failure enters NEEDS_REVIEW
with JOB_RETRY_EXHAUSTED and the cause code. retryable hints never decide this
policy. Permanent blocked/review/hold outcomes are not automatically reclaimed.
Unexpected handler exceptions become JOB_HANDLER_FAILED retries, without storing
exception text. Normal deferred/hold/review outcomes complete the handler call
but do not mark the queued job DONE.

Expired RUNNING leases record LEASE_EXPIRED and either schedule a bounded failure
retry or exhaust to review. No attempt count is added until a new claim. A stale
invocation can retain its unmatched start; recovery does not invent a successful
ending. Existing external side effects require feature-specific intent/receipt
reconciliation before replay. SQLite fencing is not external-service exactly-once.
Malformed manually created RUNNING rows (for example zero attempts) require
operator review rather than invented historical claim facts.

Storage/configuration/completion-adapter failures stop the polling loop and drain
other tasks; they do not blindly replay uncertain commits. Existing leases can
then be reconciled/recovered on a later start. A lease lost to expiry is a per-job
ownership loss. Every failure emitted by this core uses a registered safe reason;
no payloads, lease tokens, configuration values or raw exception strings are logged.

## Pause, drain and cancellation

pause/resume/stop/drain are local event-loop controls for a later transport to
invoke. They are not an implemented management API/IPC or supervisor readiness
protocol. The durable MaintenanceGate remains the cross-process admission barrier.
A stop/pause flag is checked again inside the claim transaction. A claim already
authorized before stopping is admitted work and may drain normally.

Graceful stop does not cancel running jobs. Forced task cancellation waits for
owned executor work to finish before releasing maintenance admission; repeated
cancellation cannot abandon a blocking thread in the background. Child cleanup
is shielded and drained. A noncooperative blocking handler can therefore delay
shutdown/maintenance; process isolation/forced termination would require a
separate explicit design. Interrupted work keeps its recorded lease/start for
fenced recovery; the worker does not silently reset it to PENDING.

## Remaining feature work and verification

The agreed architecture documents still guide actual business handlers. Provider
pacing, exact-resource acquisition gates, ownership receipts, artifact/decision/
import manifests and their SQL helpers are feature work, not secretly supplied
by the worker core. The authenticated management API and process supervision
remain separate components.

Offline cases cover exclusive claims, renew/expiry/stale owners, retry-versus-
defer budgeting, atomic facts/successors, adapter transaction escapes, current
configuration snapshots, same-anime concurrency, handler failures, maintenance,
shutdown and blocking cancellation. These tests are authored but **unexecuted**.
No CI, application/worker, SQL, production or media operations have been executed.
