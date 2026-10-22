"""Validated durable audit inserts, independent of log levels and scheduling.

Call only inside the same explicit transaction as the corresponding mutation.
Receipts are safe to log after a successful commit; they are not proof of commit.
"""
from dataclasses import dataclass
import json

from src.nextgen.messages import validate_event
from src.nextgen.reasons import safe_details
from src.nextgen.settings import COMPONENTS

MAX_INTEGER = (1 << 63) - 1
MAX_DETAILS_BYTES = 4096


def integer(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_INTEGER:
        raise ValueError("invalid diagnostic integer")
    return value


def component_name(component):
    if type(component) is not str or component not in COMPONENTS:
        raise ValueError("invalid diagnostic component")
    return component


def encode_details(details=None):
    if details is None:
        details = {}
    if type(details) is not dict:
        raise ValueError("invalid diagnostic details")
    allowed = {"missing_fields", "invalid_fields", "attempt", "max_attempts",
               "retry_at_ms", "cause_reason_code"}
    if any(type(key) is not str or key not in allowed for key in details):
        raise ValueError("invalid diagnostic detail key")
    encoded = json.dumps(safe_details(**details), sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_DETAILS_BYTES:
        raise ValueError("diagnostic details too large")
    return encoded


def trace_id(*, event_id=None, job_id=None):
    if event_id is not None:
        return "AD-" + str(integer(event_id, positive=True))
    if job_id is not None:
        return "JOB-" + str(integer(job_id, positive=True))
    return None


@dataclass(frozen=True)
class HistoryRecord:
    history_id: int
    scope: str
    event_code: str
    reason_code: str | None
    component: str
    occurred_at_ms: int
    event_id: int | None
    job_id: int | None
    created_by_job_id: int | None
    details_json: str


def _validate(db, scope, target_id, event_code, reason_code, component, occurred_at_ms, details):
    if not db.in_transaction:
        raise ValueError("history requires an active transaction")
    integer(target_id, positive=True)
    integer(occurred_at_ms)
    component_name(component)
    validate_event(event_code, reason_code, scope=scope)
    encoded = encode_details(details)
    # Attempts are observations of the current attempt, never scheduling policy.
    attempt = json.loads(encoded).get("attempt")
    if scope == "job" and event_code != "CREATED" and (attempt is None or attempt < 1):
        raise ValueError("positive attempt required for job lifecycle event")
    if event_code == "CREATED" and attempt not in (None, 0):
        raise ValueError("created job must have zero attempts")
    return encoded


def append_event_history(db, *, event_id, event_code, component, occurred_at_ms,
                         reason_code=None, details=None):
    encoded = _validate(db, "incoming_event", event_id, event_code, reason_code,
                        component, occurred_at_ms, details)
    if db.execute("SELECT 1 FROM incoming_events WHERE event_id=?", (event_id,)).fetchone() is None:
        raise ValueError("unknown event")
    cursor = db.execute("""INSERT INTO event_history
        (event_id,occurred_at_ms,event_code,reason_code,details_json,component)
        VALUES(?,?,?,?,?,?)""", (event_id, occurred_at_ms, event_code, reason_code, encoded, component))
    return HistoryRecord(cursor.lastrowid, "incoming_event", event_code, reason_code,
                         component, occurred_at_ms, event_id, None, None, encoded)


def append_job_history(db, *, job_id, event_code, component, occurred_at_ms,
                       reason_code=None, details=None):
    encoded = _validate(db, "job", job_id, event_code, reason_code,
                        component, occurred_at_ms, details)
    row = db.execute("SELECT event_id,created_by_job_id,attempt_count FROM jobs WHERE job_id=?",
                     (job_id,)).fetchone()
    if row is None:
        raise ValueError("unknown job")
    attempt = json.loads(encoded).get("attempt")
    if attempt is not None and attempt != row[2]:
        raise ValueError("audit attempt does not match job")
    cursor = db.execute("""INSERT INTO job_history
        (job_id,occurred_at_ms,event_code,reason_code,details_json,component)
        VALUES(?,?,?,?,?,?)""", (job_id, occurred_at_ms, event_code, reason_code, encoded, component))
    return HistoryRecord(cursor.lastrowid, "job", event_code, reason_code, component,
                         occurred_at_ms, row[0], job_id, row[1], encoded)
