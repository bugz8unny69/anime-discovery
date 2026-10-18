"""Offline cancellation orchestration. Never calls qBittorrent or acknowledges real removal.

Only use with disposable databases. An ALREADY_ABSENT result is a simulated
observation; no production action or actual external confirmation is implied.
"""
from dataclasses import dataclass
import sqlite3
from cancellation_claims import enqueue, claim, finish, ClaimError
from cancellation_preflight import Attempt, CancellationIntent, Torrent, plan, PreflightError

class OrchestrationError(ValueError):
    pass

@dataclass(frozen=True)
class Observation:
    attempt: Attempt
    decision_id: int
    decision_active: bool
    current_generation: int
    inventory: tuple
    fresh_inventory: bool


def enqueue_outbox(db, attempt_hashes):
    """Bridge trial_transition outbox to claims in a disposable DB.

    attempt_hashes: trusted dict {attempt_id: (series_id, lowercase_hash)}.
    No arbitrary fallback for unknown attempts.
    """
    if not isinstance(attempt_hashes, dict):
        raise OrchestrationError('invalid trusted bindings')
    if db.in_transaction:
        raise OrchestrationError('requires transaction-free connection')
    rows = db.execute('''SELECT o.attempt_id,o.series_id,t.status,d.action
        FROM cancellation_outbox o JOIN trial_attempts t ON t.attempt_id=o.attempt_id
        JOIN trial_decisions d ON d.series_id=o.series_id
        WHERE o.state='PENDING' ORDER BY o.attempt_id''').fetchall()
    # Validate the entire batch before enqueueing any jobs.
    for aid, sid, status, action in rows:
        if aid not in attempt_hashes or not isinstance(attempt_hashes[aid], tuple) or len(attempt_hashes[aid]) != 2:
            raise OrchestrationError('missing trusted attempt/hash binding')
        bound_sid, h = attempt_hashes[aid]
        if bound_sid != sid or status != 'CANCEL_REQUESTED' or action not in ('KEEP','REJECT'):
            raise OrchestrationError('stale outbox or wrong series')
        if not isinstance(h, str) or len(h) not in (40,64) or any(c not in '0123456789abcdef' for c in h):
            raise OrchestrationError('invalid trusted hash')
    result = []
    for aid, sid, _, _ in rows:
        result.append(enqueue(db, sid, aid, attempt_hashes[aid][1]))
    return tuple(result)


def simulate_one(db, observer, *, now, lease_seconds=60):
    """Claim, validate independently supplied snapshots, and record simulated result.

    Observer is test-controlled; this function does NOT fetch trusted external state.
    On unsafe evidence mark BLOCKED. On a matching torrent mark RETRY (never DONE).
    """
    lease = claim(db, now=now, lease_seconds=lease_seconds)
    if lease is None:
        return None
    job = db.execute('SELECT series_id,attempt_id,torrent_hash FROM cancellation_jobs WHERE id=?',
                     (lease['job_id'],)).fetchone()
    try:
        observation = observer(*job)
        if not isinstance(observation, Observation):
            raise OrchestrationError('invalid observation')
        attempt = observation.attempt
        intent = CancellationIntent(job[1],job[0],job[2],attempt.generation,observation.decision_id)
        result = plan(intent, attempt, observation.inventory,
                      decision_active=observation.decision_active,
                      fresh_inventory=observation.fresh_inventory,
                      current_generation=observation.current_generation)
        if result.result == 'ALREADY_ABSENT':
            # Simulation only: the caller must NOT treat this as real confirmation.
            outcome = 'CONFIRMED_ABSENT'
        else:
            outcome = 'RETRY'
    except (PreflightError, OrchestrationError, ValueError, TypeError, AttributeError):
        outcome = 'BLOCKED'
    state = finish(db, lease, outcome, now=now, retry_seconds=60)
    return {'job_id':lease['job_id'], 'outcome':outcome, 'state':state,
            'simulated':True, 'external_action_performed':False}
