"""Minimal job handoff metadata for existing daemon_jobs.

Jobs finish independently. An optional trigger records who queued a job;
notifications remain separate, durable Series History records.
"""
import json
import time

from anime_async_daemon import ensure_schema as ensure_jobs


def ensure_schema(db):
    ensure_jobs(db)
    db.execute("""CREATE TABLE IF NOT EXISTS anime_job_lineage (
        job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
        triggered_by_job_id INTEGER REFERENCES daemon_jobs(id),
        notification_id INTEGER,
        created_at REAL NOT NULL,
        CHECK(triggered_by_job_id IS NULL OR job_id != triggered_by_job_id)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS anime_job_triggered_by
        ON anime_job_lineage(triggered_by_job_id)""")


def enqueue_linked(db, kind, subject_key, payload, *, triggered_by_job_id=None,
                   notification_id=None, now=None):
    """Create work and its simple handoff record in one transaction.

    The first successful enqueue owns the optional triggering-job reference.
    Repeated requests for the same kind/subject with identical payload are
    idempotent, including when another job discovers the same work. The
    trigger is historical metadata, not a dependency or completion gate.
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
    if triggered_by_job_id is not None and (
            type(triggered_by_job_id) is not int or triggered_by_job_id <= 0):
        raise ValueError("Invalid triggering job")
    if notification_id is not None and (
            type(notification_id) is not int or notification_id <= 0):
        raise ValueError("Invalid notification")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        if triggered_by_job_id is not None:
            if db.execute("SELECT 1 FROM daemon_jobs WHERE id=?",
                          (triggered_by_job_id,)).fetchone() is None:
                raise ValueError("Triggering job not found")
        if notification_id is not None and db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notifications'").fetchone():
            if db.execute("SELECT 1 FROM notifications WHERE id=?",
                          (notification_id,)).fetchone() is None:
                raise ValueError("Notification not found")
        old = db.execute("""SELECT id,payload_json FROM daemon_jobs
            WHERE kind=? AND subject_key=?""", (kind, subject_key)).fetchone()
        if old:
            job_id, old_payload = old
            if old_payload != payload:
                raise ValueError("Existing job payload differs")
        else:
            job_id = db.execute("""INSERT INTO daemon_jobs
                (kind,subject_key,payload_json,state) VALUES (?,?,?,'READY')""",
                (kind, subject_key, payload)).lastrowid
        existing = db.execute("""SELECT triggered_by_job_id,notification_id
            FROM anime_job_lineage WHERE job_id=?""", (job_id,)).fetchone()
        if existing is None:
            db.execute("""INSERT INTO anime_job_lineage
                (job_id,triggered_by_job_id,notification_id,created_at)
                VALUES (?,?,?,?)""",
                (job_id, triggered_by_job_id, notification_id,
                 time.time() if now is None else now))
        # Do not overwrite a historical trigger when another notification/job
        # attempts to schedule the same exact work.
        db.commit()
        return {"job_id": job_id, "triggered_by_job_id":
                existing[0] if existing else triggered_by_job_id,
                "notification_id": existing[1] if existing else notification_id,
                "created": old is None}
    except BaseException:
        db.rollback()
        raise


def triggered_jobs(db, job_id):
    """Read-only links; downstream status never changes triggering job."""
    return db.execute("""SELECT j.id,j.kind,j.state,l.notification_id
        FROM anime_job_lineage l JOIN daemon_jobs j ON j.id=l.job_id
        WHERE l.triggered_by_job_id=? ORDER BY j.id""", (job_id,)).fetchall()
