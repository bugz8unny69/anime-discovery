"""Frozen backfill-plan snapshots, de-duplicated scheduling, and observations.

Never grants an episode reservation, media ownership, or torrent send permit.
"""
from dataclasses import dataclass
import sqlite3
import time

from src.nextgen.history import append_job_history, integer
from src.nextgen.storage.migrations import LATEST_VERSION, MigrationError, _open
from src.nextgen.storage.job_queue import QueueUnavailable
from src.nextgen.storage.sqlite import enqueue_job_with_receipt
from src.nextgen.acquisition.sonarr_search import BackfillObservation, CandidateSelection

PAGE_SIZE = 4


class BackfillConflict(ValueError):
    reason_code = 'SONARR_BACKFILL_PLAN_CONFLICT'
    def __init__(self):
        super().__init__('Frozen backfill discovery facts need review.')


@dataclass(frozen=True)
class BackfillBatch:
    plan_id: int
    anidb_id: int
    tvdb_series_id: int
    season: int
    backfill_count: int
    start: int
    numbers: tuple[int, ...]
    reserved: tuple[int, ...]
    verified: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class BackfillCompletion:
    plan: BackfillBatch
    observations: tuple[BackfillObservation, ...]


def _plan(db, plan_id, start):
    integer(plan_id, positive=True)
    integer(start, positive=True)
    row = db.execute(
        "SELECT p.anidb_id,p.tvdb_series_id,p.tvdb_season,p.backfill_count,"
        "p.anchor_episode,v.anidb_id,v.tvdb_series_id,v.tvdb_season,v.tvdb_episode "
        "FROM trial_plans p JOIN release_verifications v ON "
        "v.verification_id=p.anchor_verification_id WHERE p.plan_id=? "
        "AND p.tvdb_order='official' AND v.tvdb_order='official'", (plan_id,)
    ).fetchone()
    if row is None or (row[0],row[1],row[2],row[4]) != tuple(row[5:]):
        raise BackfillConflict()
    aid, tid, season, count = row[:4]
    if not 1 <= count <= 1000 or start > count or (start - 1) % PAGE_SIZE:
        raise BackfillConflict()
    numbers = tuple(range(start, min(count+1, start+PAGE_SIZE)))
    reserved = tuple(sorted(set(r[0] for r in db.execute(
        "SELECT tvdb_episode FROM episode_reservations WHERE "
        "tvdb_series_id=? AND tvdb_season=? AND state='ACTIVE' "
        "AND tvdb_episode BETWEEN ? AND ? UNION "
        "SELECT tvdb_episode FROM batch_episode_reservations WHERE "
        "tvdb_series_id=? AND tvdb_season=? AND state='ACTIVE' "
        "AND tvdb_episode BETWEEN ? AND ?",
        (tid, season, numbers[0], numbers[-1], tid, season, numbers[0], numbers[-1])
    ))))
    known = tuple(db.execute(
        "SELECT tvdb_episode,tvdb_episode_id FROM recognized_episodes WHERE "
        "anidb_id=? AND tvdb_series_id=? AND tvdb_season=? AND "
        "tvdb_episode BETWEEN ? AND ? ORDER BY tvdb_episode",
        (aid, tid, season, numbers[0], numbers[-1])
    ).fetchall())
    return BackfillBatch(plan_id,aid,tid,season,count,start,numbers,reserved,known)


def load_batch(database, plan_id, start):
    db = None
    try:
        db = _open(database,readonly=True,timeout_ms=5000)
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != LATEST_VERSION:
            raise QueueUnavailable()
        return _plan(db,plan_id,start)
    except (sqlite3.Error,OSError,MigrationError):
        raise QueueUnavailable() from None
    finally:
        if db is not None: db.close()


def schedule_first(db, claim, source, *, kind):
    """Exactly one first page per frozen plan, in evaluation completion TX."""
    if not db.in_transaction: raise ValueError('worker transaction required')
    row = db.execute(
        "SELECT p.plan_id,p.backfill_count FROM trial_plans p WHERE "
        "p.anidb_id=? AND p.tvdb_series_id=? AND p.tvdb_season=? "
        "AND p.tvdb_order='official'",
        (source.anidb_id,source.tvdb_series_id,source.tvdb_season)
    ).fetchone()
    if row is None: raise BackfillConflict()
    plan_id,count = row
    if not count: return ()
    # Transaction is already a SQLite write transaction. Concurrent evaluation
    # completions serialize here; later deliveries cannot schedule a replay.
    exists = db.execute(
        "SELECT 1 FROM jobs WHERE kind=? AND "
        "json_extract(payload_json,'$.plan_id')=? LIMIT 1",(kind,plan_id)
    ).fetchone()
    if exists: return ()
    op = db.execute(
        "SELECT operation_id FROM job_operation_members WHERE job_id=?",
        (claim.job_id,)
    ).fetchone()
    if op is None: raise BackfillConflict()
    _,receipt = enqueue_job_with_receipt(
        db,component='worker',kind=kind,payload={'plan_id':plan_id,'start':1},
        event_id=claim.event_id,created_by_job_id=claim.job_id,
        operation_id=op[0]
    )
    return (receipt,)


def persist_observations(db, claim, value):
    if not db.in_transaction or type(value) is not BackfillCompletion:
        raise ValueError('worker transaction and typed results required')
    plan = value.plan
    if len(value.observations) != len(plan.numbers):
        raise BackfillConflict()
    # Recheck immutable scope. Reservation state is intentionally not re-queried
    # here: it may change after a read-only search; this is observation, not
    # authorization.
    current = _plan(db,plan.plan_id,plan.start)
    if (current.plan_id,current.anidb_id,current.tvdb_series_id,
        current.season,current.backfill_count,current.numbers) != (
        plan.plan_id,plan.anidb_id,plan.tvdb_series_id,plan.season,
        plan.backfill_count,plan.numbers):
        raise BackfillConflict()
    if claim.event_id is None: raise BackfillConflict()
    for number,item in zip(plan.numbers,value.observations):
        if (type(item) is not BackfillObservation or item.number != number
                or item.status not in ('IN_PROGRESS','NOT_LISTED','IDENTITY_UNKNOWN',
                                       'IDENTITY_CONFLICT','HAS_FILE','CANDIDATES','NO_RESULTS')
                or not 0 <= item.approved <= item.candidates <= 1000
                or not 0 <= item.exact <= item.candidates <= 1000
                or item.status != 'CANDIDATES' and (item.candidates or item.approved or item.exact)):
            raise BackfillConflict()
        previous = db.execute(
            'SELECT 1 FROM sonarr_backfill_results WHERE plan_id=? AND tvdb_episode=?',
            (plan.plan_id,number)
        ).fetchone()
        if previous: raise BackfillConflict()
    now = integer(time.time_ns() // 1000000)
    # Selection is an opt-in side effect of the same fenced worker completion.
    # Keep source URLs out of SQLite and reject stale/unverified identity facts.
    from src.nextgen.storage.sonarr_selection import select, SelectionConflict
    for item in value.observations:
        choice = item.selection
        if choice is not None:
            if (type(choice) is not CandidateSelection or item.status != 'CANDIDATES'
                    or item.tvdb_episode_id != choice.identity.tvdb_episode_id
                    or item.number != choice.identity.tvdb_episode
                    or plan.tvdb_series_id != choice.identity.tvdb_series_id
                    or plan.season != choice.identity.tvdb_season
                    or dict(plan.verified).get(item.number) != item.tvdb_episode_id):
                raise BackfillConflict()
            try:
                select(db, plan_id=plan.plan_id, identity=choice.identity,
                       result=choice.result, release=choice.release, policy=choice.policy)
            except SelectionConflict:
                raise BackfillConflict() from None
        db.execute(
            "INSERT INTO sonarr_backfill_results("
            "plan_id,tvdb_episode,job_id,sonarr_episode_id,tvdb_episode_id,status,"
            "candidates,approved,exact,observed_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (plan.plan_id,item.number,claim.job_id,item.sonarr_episode_id,
             item.tvdb_episode_id,item.status,item.candidates,item.approved,
             item.exact,now)
        )
    return (append_job_history(db,job_id=claim.job_id,
        event_code='SONARR_BACKFILL_OBSERVED',component='worker',occurred_at_ms=now,
        details={'attempt':claim.attempt}),)
