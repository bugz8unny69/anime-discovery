# Review retry storage contract for API / worker implementers

Draft: unmerged; no database migration, runtime endpoint, auth change or worker
handler changes. This feature applies to NextGen only.

## Export

from src.nextgen.storage.review_retry import request_review_retry, RetryNotAllowed, RetryStale

request_review_retry(database_path, job_id, expected_attempt=N,
                     expected_reason="RELEASE_EPISODE_MAPPING_MISSING")

Returns RetryReceipt(job_id, attempt, outcome, history_id).
outcome is QUEUED or ALREADY_QUEUED.

## Endpoint integration

- Authenticate the administrator using normal session and CSRF protections.
- Validate request origin and exact positive job ID / attempt / reason fields.
- Read the current snapshot in the usual authenticated jobs API; supply
  its attempt and last_reason_code to request_review_retry.
- Map RetryStale to a conflict response and RetryNotAllowed to an unavailable
  action. Never silently retry a stale, running, completed or canceled job.
- Do not return internal database paths, worker leases, request tokens or
  untrusted provider payloads.

## Current retry policy

- Only NEEDS_REVIEW IDENTIFY_ANIME and VERIFY_RELEASE jobs with at least one
  prior attempt and an exact matching last reason are eligible.
- Keeps existing job_id, event_id, payload, attempt history and provenance.
- Clears last_reason_code and activity, atomically moves to PENDING and
  appends RETRY_REQUESTED audit with component api and prior attempt.
- Rejects active/expired worker leases, inactive or canceled operations,
  any existing successor job, stale snapshots and all jobs with external
  torrent/media/Keep/Reject/cleanup side effects.
- Idempotently acknowledges repeated identical requests while still PENDING.
- Existing worker PENDING claim path may process the job; worker and endpoint
  integration/reconciliation rules are owned by the other chat.

## Tests and operations

Added offline test_review_retry.py. No full tests or CI were run at user request.
Commits include [skip ci]. No manual deployment or production DB changes.
