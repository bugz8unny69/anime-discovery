"""Postfix-style asynchronous daemon scheduler primitives.

One asyncio event loop, bounded workers, SQLite leases. Database connections
are short-lived and never held across network or filesystem awaits.
"""
import asyncio
import sqlite3
import time
import uuid

LEASE_SECONDS = 300

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_jobs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        subject_key TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('READY','LEASED','DEFERRED','NEEDS_REVIEW','DONE','BLOCKED')),
        available_at REAL NOT NULL DEFAULT 0,
        lease_token TEXT,
        lease_until REAL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        UNIQUE(kind,subject_key)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS daemon_jobs_ready ON daemon_jobs(state,available_at,lease_until)")

def enqueue(db, kind, subject_key, payload_json):
    if db.in_transaction:
        raise ValueError("enqueue requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        db.execute("INSERT OR IGNORE INTO daemon_jobs(kind,subject_key,payload_json,state) VALUES (?,?,?,'READY')",
                   (kind,subject_key,payload_json))
        db.commit()
    except BaseException:
        db.rollback()
        raise

def claim(db, now=None, *, lease_seconds=LEASE_SECONDS):
    if type(lease_seconds) is not int or lease_seconds < 30:
        raise ValueError('Invalid lease duration')
    if db.in_transaction:
        raise ValueError("claim requires autocommit connection")
    now=time.time() if now is None else now
    token=uuid.uuid4().hex
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        row=db.execute("""SELECT id,kind,subject_key,payload_json,attempts FROM daemon_jobs
            WHERE (state IN ('READY','DEFERRED') AND available_at<=?)
               OR (state='LEASED' AND lease_until<?)
            ORDER BY available_at,id LIMIT 1""",(now,now)).fetchone()
        if row:
            db.execute("""UPDATE daemon_jobs SET state='LEASED',lease_token=?,lease_until=?,
                attempts=attempts+1 WHERE id=?""",(token,now+lease_seconds,row[0]))
        db.commit()
        return dict(zip(("id","kind","subject_key","payload_json","attempts"),row)) | {"lease_token":token} if row else None
    except BaseException:
        db.rollback()
        raise

def renew(db, job_id, token, *, lease_seconds=LEASE_SECONDS, now=None):
    """Extend only the current unexpired lease; stale workers cannot renew."""
    if type(lease_seconds) is not int or lease_seconds < 30:
        raise ValueError("Invalid lease duration")
    if db.in_transaction:
        raise ValueError("renew requires autocommit connection")
    now=time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        cursor=db.execute("""UPDATE daemon_jobs SET lease_until=?
            WHERE id=? AND state='LEASED' AND lease_token=? AND lease_until>=?""",
            (now+lease_seconds,job_id,token,now))
        if cursor.rowcount!=1:
            raise ValueError("Stale or expired lease")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def finish(db, job_id, token, outcome, *, reason="", now=None):
    if outcome not in ("DONE","DEFERRED","NEEDS_REVIEW","BLOCKED"):
        raise ValueError("Invalid outcome")
    if db.in_transaction:
        raise ValueError("finish requires autocommit connection")
    now=time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT attempts FROM daemon_jobs WHERE id=? AND state='LEASED' AND lease_token=?",(job_id,token)).fetchone()
        if row is None:
            raise ValueError("Stale or missing lease")
        delay=min(3600, 5 * 2 ** min(row[0]-1,10)) if outcome=="DEFERRED" else 0
        db.execute("""UPDATE daemon_jobs SET state=?,available_at=?,lease_token=NULL,
            lease_until=NULL,last_error=? WHERE id=?""",(outcome,now+delay,reason,job_id))
        db.commit()
    except BaseException:
        db.rollback()
        raise

async def run_workers(db_path, handlers, *, concurrency=4, poll_seconds=1.0, stop=None, config_manager=None):
    """Run bounded concurrent handlers. Handlers must be async and idempotent.

    A handler returns DONE, DEFERRED, NEEDS_REVIEW, or BLOCKED. Exceptions
    are retried; cancellation leaves a lease for later recovery.
    """
    if not 1<=concurrency<=32:
        raise ValueError("Invalid concurrency")
    stop=stop or asyncio.Event()
    if config_manager is not None:
        await config_manager.reload_if_changed()
    async def worker():
        while not stop.is_set():
            with sqlite3.connect(db_path,isolation_level=None,timeout=10) as db:
                db.execute("PRAGMA busy_timeout=10000")
                lease_seconds=(config_manager.snapshot.settings['daemon']['lease_seconds']
                               if config_manager is not None else LEASE_SECONDS)
                job=claim(db,lease_seconds=lease_seconds)
            if job is None:
                try:
                    await asyncio.wait_for(stop.wait(),timeout=poll_seconds)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                if config_manager is not None:
                    try:
                        snapshot=await config_manager.reload_if_changed()
                    except (ValueError, OSError):
                        # Invalid admin edit must not interrupt ongoing work.
                        snapshot=config_manager.snapshot
                    job["config_snapshot"]=snapshot
                handler=handlers[job["kind"]]
                async def keep_alive():
                    while True:
                        await asyncio.sleep(max(1,lease_seconds/3))
                        with sqlite3.connect(db_path,isolation_level=None,timeout=10) as heartbeat_db:
                            renew(heartbeat_db,job['id'],job['lease_token'],lease_seconds=lease_seconds)
                heartbeat=asyncio.create_task(keep_alive())
                try:
                    outcome=await handler(job)
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
                if outcome not in ("DONE","DEFERRED","NEEDS_REVIEW","BLOCKED"):
                    raise ValueError("Invalid handler result")
                reason=""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                outcome="DEFERRED"
                reason=type(exc).__name__
            with sqlite3.connect(db_path,isolation_level=None,timeout=10) as db:
                finish(db,job["id"],job["lease_token"],outcome,reason=reason)
    await asyncio.gather(*(worker() for _ in range(concurrency)))
