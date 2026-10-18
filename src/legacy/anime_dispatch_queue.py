"""Controller dispatch queue: durable, idempotent work claims.

No torrent operations are performed by this module. The returned claim is
permission to attempt downstream verification, not evidence of a download.
"""
import sqlite3
import time

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS episode_dispatch (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        series_id INTEGER NOT NULL REFERENCES series(id),
        season INTEGER NOT NULL CHECK(season > 0),
        episode INTEGER NOT NULL CHECK(episode > 0),
        state TEXT NOT NULL CHECK(state IN ('READY','CLAIMED','DONE','NEEDS_REVIEW')),
        attempts INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        last_error TEXT
    )""")

def enqueue_approved(db, limit=100):
    """Import approvals without replacing existing dispatch state."""
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid limit")
    if db.in_transaction:
        raise ValueError("Requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        rows=db.execute("""SELECT q.notification_id,q.series_id,q.season,q.episode
            FROM episode_approval_queue q
            JOIN series s ON s.id=q.series_id
            WHERE q.decision='AUTO_APPROVED' AND q.season IS NOT NULL
              AND q.episode IS NOT NULL AND s.status!='REJECTED'
              AND NOT EXISTS(SELECT 1 FROM series_rejection_blocks b WHERE b.series_id=q.series_id)
              AND NOT EXISTS(SELECT 1 FROM migration_quarantined_series x WHERE x.series_id=q.series_id)
              AND NOT EXISTS(SELECT 1 FROM episode_dispatch d WHERE d.notification_id=q.notification_id)
            ORDER BY q.notification_id LIMIT ?""",(limit,)).fetchall()
        now=int(time.time())
        db.executemany("""INSERT INTO episode_dispatch
            (notification_id,series_id,season,episode,state,updated_at)
            VALUES (?,?,?,?,'READY',?)""",[(a,b,c,d,now) for a,b,c,d in rows])
        db.commit()
        return len(rows)
    except BaseException:
        db.rollback()
        raise

def claim_next(db):
    """Claim one ready job; reject/quarantine is rechecked under write lock."""
    if db.in_transaction:
        raise ValueError("Requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("""SELECT d.notification_id,d.series_id,d.season,d.episode
            FROM episode_dispatch d JOIN series s ON s.id=d.series_id
            JOIN episode_approval_queue q ON q.notification_id=d.notification_id
            WHERE d.state='READY' AND q.decision='AUTO_APPROVED'
              AND s.status!='REJECTED'
              AND NOT EXISTS(SELECT 1 FROM series_rejection_blocks b WHERE b.series_id=d.series_id)
              AND NOT EXISTS(SELECT 1 FROM migration_quarantined_series x WHERE x.series_id=d.series_id)
            ORDER BY d.notification_id LIMIT 1""").fetchone()
        if row:
            db.execute("UPDATE episode_dispatch SET state='CLAIMED',attempts=attempts+1,updated_at=? WHERE notification_id=?",(int(time.time()),row[0]))
        db.commit()
        return dict(zip(("notification_id","series_id","season","episode"),row)) if row else None
    except BaseException:
        db.rollback()
        raise

def complete(db, notification_id, *, success, reason=""):
    """A downstream verifier calls this only after actual completion evidence."""
    if db.in_transaction:
        raise ValueError("Requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT state FROM episode_dispatch WHERE notification_id=?",(notification_id,)).fetchone()
        if row != ("CLAIMED",):
            raise ValueError("Only claimed work can be completed")
        state="DONE" if success else "NEEDS_REVIEW"
        db.execute("UPDATE episode_dispatch SET state=?,last_error=?,updated_at=? WHERE notification_id=?",(state,reason,int(time.time()),notification_id))
        db.commit()
    except BaseException:
        db.rollback()
        raise

def reclaim_expired_claims(db, *, now=None, older_than_seconds=3600, limit=100):
    """Conservatively release abandoned claims only when no daemon job owns them.

    An active or previously scheduled acquisition job remains authoritative;
    it must be reconciled instead of creating a second dispatch.
    """
    if db.in_transaction:
        raise ValueError("Requires autocommit connection")
    if type(older_than_seconds) is not int or older_than_seconds<300:
        raise ValueError("Invalid recovery interval")
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError("Invalid recovery limit")
    now=int(time.time()) if now is None else int(now)
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        # Fail closed if the daemon schema has not been migrated.
        present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daemon_jobs'").fetchone()
        if not present:
            raise ValueError("Daemon job schema missing")
        rows=db.execute("""SELECT d.notification_id FROM episode_dispatch d
            JOIN series s ON s.id=d.series_id
            JOIN episode_approval_queue q ON q.notification_id=d.notification_id
            WHERE d.state='CLAIMED' AND d.updated_at<?
              AND q.decision='AUTO_APPROVED' AND s.status!='REJECTED'
              AND NOT EXISTS(SELECT 1 FROM series_rejection_blocks b WHERE b.series_id=d.series_id)
              AND NOT EXISTS(SELECT 1 FROM migration_quarantined_series x WHERE x.series_id=d.series_id)
              AND NOT EXISTS(SELECT 1 FROM daemon_jobs j
                  WHERE j.kind='claimed_acquisition' AND j.subject_key=CAST(d.notification_id AS TEXT))
            ORDER BY d.updated_at,d.notification_id LIMIT ?""",
            (now-older_than_seconds,limit)).fetchall()
        for (notification_id,) in rows:
            db.execute("""UPDATE episode_dispatch SET state='READY',
                last_error='Recovered abandoned claim',updated_at=?
                WHERE notification_id=? AND state='CLAIMED'""",(now,notification_id))
        db.commit()
        return len(rows)
    except BaseException:
        db.rollback()
        raise
