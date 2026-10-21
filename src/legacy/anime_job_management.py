"""Transactional operator controls for daemon jobs.

SQLite's existing daemon_jobs CHECK constraint intentionally remains unchanged:
a canceled job is recorded as BLOCKED with an immutable cancellation event.
This avoids rebuilding production tables just to add a new display state.
Only waiting jobs may be changed. Active leases are never seized.
"""
import sqlite3
from pathlib import Path
import json
from anime_cleanup_review import inventory
import time

MANAGEABLE_KINDS=("claimed_acquisition","series_gap_search","verified_batch_acquisition")

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_job_admin_events (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES daemon_jobs(id),
        action TEXT NOT NULL CHECK(action IN ('retry','cancel')),
        previous_state TEXT NOT NULL,
        previous_attempts INTEGER NOT NULL,
        previous_error TEXT,
        created_at REAL NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_job_archived_subjects (
        job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
        kind TEXT NOT NULL, original_subject_key TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_job_cleanup_review (
        job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
        status TEXT NOT NULL CHECK(status IN ('REVIEW_REQUIRED','NOT_VERIFIED')),
        candidate_hashes_json TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS daemon_job_admin_events_latest
        ON daemon_job_admin_events(job_id,id)""")

def latest_events(db):
    """Read-only presentation data; handles databases not yet upgraded."""
    if not db.execute("""SELECT 1 FROM sqlite_master
                         WHERE type='table' AND name='daemon_job_admin_events'""").fetchone():
        return {}
    rows=db.execute("""SELECT e.job_id,e.action,e.previous_state,e.previous_error,
            e.created_at FROM daemon_job_admin_events e
            WHERE e.id=(SELECT MAX(id) FROM daemon_job_admin_events
                        WHERE job_id=e.job_id)""").fetchall()
    return {int(job_id):{"action":action,"previous_state":old,
                         "previous_error":error,"at":at}
            for job_id,action,old,error,at in rows}

def has_staged_media(db, kind, subject_key):
    """Protect completed staged batch episodes from job cancellation.

    Uses durable staging records (rather than mere filename existence).
    Never mutate the filesystem during review or cancellation.
    """
    tables={row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if kind=="claimed_acquisition":
        if "episode_dispatch" in tables and db.execute(
            """SELECT 1 FROM episode_dispatch WHERE notification_id=?
               AND state='DONE' LIMIT 1""",(subject_key,)).fetchone():
            return True
        if "torrent_recovery_records" in tables:
            for (path,) in db.execute("""SELECT staged_path FROM torrent_recovery_records
                WHERE notification_id=?""",(subject_key,)):
                if path and (Path(path).exists() or Path(path).is_symlink()):
                    return True
        return False
    if kind != "verified_batch_acquisition":
        return False
    if "anime_batch_staged" not in tables:
        return False
    if "anime_batch_authorizations" not in tables:
        # Staging evidence exists but provenance cannot be linked safely.
        # Refuse destructive cancellation pending schema reconciliation.
        return True
    return bool(db.execute("""SELECT 1
        FROM anime_batch_authorizations a
        JOIN anime_batch_staged s ON s.tvdb_id=a.tvdb_id
            AND s.anidb_id=a.anidb_id AND s.season=a.season
            AND s.unit_key=a.unit_key AND s.infohash=a.infohash
        WHERE a.notification_id=? LIMIT 1""",(subject_key,)).fetchone())


def manage(db, job_id, operation, *, expected_state, expected_attempts, now=None):
    """Compare-and-swap an idle job; preserve the attempt and error history.

    - retry: NEEDS_REVIEW -> READY, only by explicit administrator action
    - cancel: NEEDS_REVIEW -> BLOCKED, archived subject and audit event
    Neither changes payload, identity, qBittorrent, dispatch, or media.
    """
    if type(job_id) is not int or job_id<=0:
        raise ValueError("Valid job ID required")
    if operation not in ("retry","cancel"):
        raise ValueError("Unknown job action")
    if type(expected_attempts) is not int or expected_attempts<0:
        raise ValueError("Expected attempt count required")
    if expected_state!="NEEDS_REVIEW":
        raise ValueError("Expected waiting job state required")
    if db.in_transaction:
        raise ValueError("Job management requires autocommit connection")
    now=time.time() if now is None else now
    if type(now) not in (int,float):
        raise ValueError("Invalid operation time")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        row=db.execute("""SELECT kind,state,attempts,last_error,subject_key
            FROM daemon_jobs WHERE id=?""",(job_id,)).fetchone()
        if row is None:
            raise ValueError("Job not found")
        kind,state,attempts,error,subject_key=row
        if kind not in MANAGEABLE_KINDS:
            raise ValueError("Unsupported job kind")
        if state!=expected_state or attempts!=expected_attempts:
            raise ValueError("Job changed; refresh and try again")
        if operation=="retry" and state!="NEEDS_REVIEW":
            raise ValueError("Only needs-review jobs can be manually retried")
        if operation=="cancel" and state!="NEEDS_REVIEW":
            raise ValueError("Only needs-review jobs can be canceled")
        if operation=="cancel" and has_staged_media(db,kind,subject_key):
            raise ValueError("Staged episodes require completion recovery, not cancellation")
        new_state="READY" if operation=="retry" else "BLOCKED"
        # Compare-and-swap under a write lock prevents racing claim/retry
        # across dashboard requests and all workers. Do not reset attempts.
        changed=db.execute("""UPDATE daemon_jobs SET state=?,available_at=0,
            lease_token=NULL,lease_until=NULL
            WHERE id=? AND kind=? AND state=? AND attempts=?
            AND lease_token IS NULL""",
            (new_state,job_id,kind,state,attempts)).rowcount
        if changed!=1:
            raise ValueError("Job is leased or changed; refresh and try again")
        if operation=="cancel":
            resources=inventory(db,kind,subject_key)
            db.execute("""INSERT INTO daemon_job_cleanup_review
                (job_id,status,candidate_hashes_json,created_at) VALUES (?,?,?,?)""",
                (job_id,resources["cleanup_status"],
                 json.dumps(resources["candidate_hashes"]),now))
            db.execute("""INSERT INTO daemon_job_archived_subjects
                (job_id,kind,original_subject_key) VALUES (?,?,?)""",
                (job_id,kind,subject_key))
            db.execute("""UPDATE daemon_jobs SET subject_key=?
                WHERE id=? AND state='BLOCKED'""",
                ("archived:"+str(job_id)+":"+subject_key,job_id))
        db.execute("""INSERT INTO daemon_job_admin_events
            (job_id,action,previous_state,previous_attempts,previous_error,created_at)
            VALUES (?,?,?,?,?,?)""",(job_id,operation,state,attempts,error,now))
        db.commit()
        return {"ok":True,"job_id":job_id,"action":operation,"state":new_state,
                "attempts":attempts,"last_error":error}
    except BaseException:
        db.rollback()
        raise
