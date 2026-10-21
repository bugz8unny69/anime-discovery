"""Additive durable job lineage for the existing daemon_jobs queue.

Notifications remain separate series-history evidence. Lineage is opt-in until
existing workflows are migrated and never alters daemon job state or retries.
"""
import json
import sqlite3
import time

from anime_async_daemon import ensure_schema as ensure_jobs


def ensure_schema(db):
    ensure_jobs(db)
    db.execute("""CREATE TABLE IF NOT EXISTS anime_job_lineage (
        job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
        parent_job_id INTEGER REFERENCES daemon_jobs(id),
        root_job_id INTEGER NOT NULL REFERENCES daemon_jobs(id),
        origin_notification_id INTEGER,
        created_at REAL NOT NULL,
        CHECK(parent_job_id IS NULL OR job_id != parent_job_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS anime_job_lineage_root ON anime_job_lineage(root_job_id)")
    db.execute("CREATE INDEX IF NOT EXISTS anime_job_lineage_parent ON anime_job_lineage(parent_job_id)")
    # No notification FK: old standalone daemon queue tests/databases do not
    # necessarily have notifications. Validate the reference where available.


def enqueue_linked(db, kind, subject_key, payload, *, parent_job_id=None,
                   origin_notification_id=None, now=None):
    """Atomically enqueue a job and its immutable lineage.

    Existing legacy jobs may be adopted. Conflicting payloads or ancestry
    fail closed; a repeated request with identical evidence is idempotent.
    Caller must use an autocommit SQLite connection.
    """
    if db.in_transaction:
        raise ValueError("Linked enqueue requires autocommit connection")
    if not isinstance(kind, str) or not kind or not isinstance(subject_key, str) or not subject_key:
        raise ValueError("Job identity required")
    if not isinstance(payload, str):
        raise ValueError("Serialized job payload required")
    try:
        json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid JSON job payload") from exc
    if parent_job_id is not None and (type(parent_job_id) is not int or parent_job_id <= 0):
        raise ValueError("Invalid parent job")
    if origin_notification_id is not None and (
            type(origin_notification_id) is not int or origin_notification_id <= 0):
        raise ValueError("Invalid origin notification")
    now = time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        parent = None
        if parent_job_id is not None:
            parent = db.execute("""SELECT root_job_id,origin_notification_id
                FROM anime_job_lineage WHERE job_id=?""", (parent_job_id,)).fetchone()
            if parent is None:
                raise ValueError("Parent job requires existing lineage")
            if origin_notification_id is None:
                origin_notification_id = parent[1]
            elif parent[1] is not None and origin_notification_id != parent[1]:
                raise ValueError("Child notification differs from parent")
        if origin_notification_id is not None and db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notifications'").fetchone():
            if db.execute("SELECT 1 FROM notifications WHERE id=?",
                          (origin_notification_id,)).fetchone() is None:
                raise ValueError("Origin notification not found")
        old = db.execute("SELECT id,payload_json FROM daemon_jobs WHERE kind=? AND subject_key=?",
                         (kind, subject_key)).fetchone()
        if old:
            job_id, old_payload = old
            if old_payload != payload:
                raise ValueError("Existing job payload differs")
        else:
            job_id = db.execute("""INSERT INTO daemon_jobs
                (kind,subject_key,payload_json,state) VALUES (?,?,?,'READY')""",
                (kind, subject_key, payload)).lastrowid
        root = parent[0] if parent else job_id
        old_link = db.execute("""SELECT parent_job_id,root_job_id,origin_notification_id
            FROM anime_job_lineage WHERE job_id=?""", (job_id,)).fetchone()
        proposed = (parent_job_id, root, origin_notification_id)
        if old_link and old_link != proposed:
            raise ValueError("Existing job lineage conflicts")
        if not old_link:
            db.execute("""INSERT INTO anime_job_lineage
                (job_id,parent_job_id,root_job_id,origin_notification_id,created_at)
                VALUES (?,?,?,?,?)""", (job_id, *proposed, now))
        db.commit()
        return {"job_id": job_id, "root_job_id": root,
                "parent_job_id": parent_job_id, "origin_notification_id": origin_notification_id,
                "created": old is None}
    except BaseException:
        db.rollback()
        raise


def children(db, parent_job_id):
    """Read-only immediate descendants; job outcomes remain independent."""
    return db.execute("""SELECT j.id,j.kind,j.state,l.origin_notification_id
        FROM anime_job_lineage l JOIN daemon_jobs j ON j.id=l.job_id
        WHERE l.parent_job_id=? ORDER BY j.id""", (parent_job_id,)).fetchall()
