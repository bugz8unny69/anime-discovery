"""Durable compare-and-set retry requests for safe pre-acquisition review jobs.

Not an API route or a forced general requeue. External torrent/media/
Keep/Reject/cleanup operations require handler-specific reconciliation first.
"""
from dataclasses import dataclass

from src.nextgen.history import append_job_history, integer
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction

SAFE_RETRY_KINDS = frozenset(("IDENTIFY_ANIME", "VERIFY_RELEASE"))


class RetryNotAllowed(ValueError):
    """State, kind, cancellation or successor makes requeue unsafe."""


class RetryStale(ValueError):
    """Caller based a retry on outdated job status/attempt/reason."""


@dataclass(frozen=True)
class RetryReceipt:
    job_id: int
    attempt: int
    outcome: str
    history_id: int


def request_review_retry(database, job_id, *, expected_attempt, expected_reason, clock=None):
    """Atomically requeue one safe NEEDS_REVIEW job; return durable audit receipt.

    The endpoint must authorize the caller (session, CSRF and origin) BEFORE
    calling this storage function. The expected attempt and review reason
    must come from the last displayed snapshot. Repeated identical requests
    while still queued are idempotent. The worker can claim normal PENDING
    jobs without lease revocation or direct worker invocation.
    """
    job_id = integer(job_id, positive=True)
    expected_attempt = integer(expected_attempt, positive=True)
    if type(expected_reason) is not str or not 1 <= len(expected_reason) <= 64:
        raise ValueError("expected review reason required")
    queue = JobQueue(database, clock=clock)
    with queue.connection() as db, transaction(db):
        now = queue.now()
        row = db.execute(
            "SELECT kind,state,attempt_count,last_reason_code,lease_token,lease_expires_at_ms "
            "FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise RetryNotAllowed("unknown job")
        kind, state, attempt, reason, token, expires = row
        if kind not in SAFE_RETRY_KINDS:
            raise RetryNotAllowed("review of this job kind requires resource-specific reconciliation")
        if attempt != expected_attempt:
            raise RetryStale("job attempt changed")
        if state == "PENDING":
            previous = db.execute(
                "SELECT history_id FROM job_history WHERE job_id=? "
                "AND event_code='RETRY_REQUESTED' ORDER BY history_id DESC LIMIT 1",
                (job_id,)).fetchone()
            if previous is not None and token is None and expires is None:
                return RetryReceipt(job_id, attempt, "ALREADY_QUEUED", previous[0])
        if state != "NEEDS_REVIEW":
            raise RetryNotAllowed("only NEEDS_REVIEW jobs can be manually requeued")
        if reason != expected_reason:
            raise RetryStale("review reason changed")
        if token is not None or expires is not None:
            raise RetryNotAllowed("job has outstanding lease information")
        if db.execute("SELECT 1 FROM jobs WHERE created_by_job_id=? LIMIT 1", (job_id,)).fetchone():
            raise RetryNotAllowed("job has already created successor work")
        operation = db.execute(
            "SELECT o.state FROM job_operation_members m "
            "JOIN job_operations o ON o.operation_id=m.operation_id "
            "WHERE m.job_id=?", (job_id,)).fetchone()
        if operation is not None and operation[0] != "ACTIVE":
            raise RetryNotAllowed("operation is no longer active")
        changed = db.execute(
            "UPDATE jobs SET state='PENDING',available_at_ms=?,updated_at_ms=?,"
            "last_reason_code=NULL,activity_code=NULL "
            "WHERE job_id=? AND state='NEEDS_REVIEW' AND attempt_count=? "
            "AND last_reason_code=? AND lease_token IS NULL AND lease_expires_at_ms IS NULL",
            (now, now, job_id, attempt, reason))
        if changed.rowcount != 1:
            raise RetryStale("job was updated concurrently")
        audit = append_job_history(
            db, job_id=job_id, event_code="RETRY_REQUESTED", component="api",
            occurred_at_ms=now, details={"attempt": attempt})
        return RetryReceipt(job_id, attempt, "QUEUED", audit.history_id)
