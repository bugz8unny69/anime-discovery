"""Unified-database review reminder scheduler; never mutates acquisition state."""
from anime_diagnostics import configure_logging, event
import sqlite3
import re
import time
from anime_config_wakeup import wait_for_change
import logging
LOG=logging.getLogger(__name__)
from pathlib import Path
from anime_flat_config import load_config
from anime_ntfy import notify_best_effort

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ntfy_delivery (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        sent_at INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS ntfy_job_delivery (
        job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
        sent_at INTEGER NOT NULL
    )""")

def mark_sent(db, notification_id, *, now=None):
    if not isinstance(notification_id,int) or notification_id<=0:
        raise ValueError("Invalid notification ID")
    ensure_schema(db)
    db.execute("""INSERT INTO ntfy_delivery(notification_id,sent_at) VALUES (?,?)
        ON CONFLICT(notification_id) DO UPDATE SET sent_at=excluded.sent_at""",
        (notification_id,int(time.time()) if now is None else int(now)))

def check_once(db, settings, secrets, *, now=None, sender=notify_best_effort):
    if not settings["ntfy"]["enabled"]:
        return {"sent":0,"pending":0}
    now=int(time.time()) if now is None else int(now)
    ensure_schema(db)
    interval=max(3600,settings["ntfy"]["reminder_hours"]*3600)
    # Identity and acquisition reviews are separate durable state machines.
    # The former still requires finalized triage evidence; a terminal
    # NEEDS_REVIEW acquisition job is independently actionable.
    has_identity=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_identity_checks'").fetchone()
    rows=db.execute("""SELECT n.id,n.release_name FROM notifications n
        LEFT JOIN episode_dispatch d ON d.notification_id=n.id
        JOIN unified_identity_checks c ON c.notification_id=n.id
        LEFT JOIN ntfy_delivery sent ON sent.notification_id=n.id
        WHERE d.notification_id IS NULL AND n.status='NEEDS_REVIEW'
          AND c.decision IN ('NEEDS_REVIEW',
              'SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED')
          AND c.next_at=0
          AND c.checked_at>=n.received_at
          AND (sent.sent_at IS NULL OR sent.sent_at<=?)
        ORDER BY n.id ASC LIMIT 50""",(now-interval,)).fetchall() if has_identity else []
    jobs=db.execute("""SELECT j.id,j.kind,j.last_error FROM daemon_jobs j
        LEFT JOIN ntfy_job_delivery sent ON sent.job_id=j.id
        WHERE j.state='NEEDS_REVIEW'
          AND (sent.sent_at IS NULL OR sent.sent_at<=?)
        ORDER BY j.id ASC LIMIT 50""",(now-interval,)).fetchall()
    sent=0
    for notification_id,title in rows:
        if sender(settings,secrets,notification_id,title):
            mark_sent(db,notification_id,now=now)
            sent+=1
    for job_id,kind,last_error in jobs:
        reason=str(last_error or "HANDLER_NEEDS_REVIEW")
        reason=reason if re.fullmatch(r"[A-Za-z0-9_]{1,70}",reason) else "HANDLER_NEEDS_REVIEW"
        safe_kind=str(kind) if re.fullmatch(r"[a-z_]{1,65}",str(kind)) else "acquisition"
        summary="Job %d (%s) blocked: %s"%(job_id,safe_kind,reason)
        if sender(settings,secrets,job_id,summary):
            db.execute("""INSERT INTO ntfy_job_delivery(job_id,sent_at) VALUES (?,?)
                ON CONFLICT(job_id) DO UPDATE SET sent_at=excluded.sent_at""",
                (job_id,now))
            sent+=1
    return {"sent":sent,"pending":len(rows)+len(jobs)}

def main():
    configure_logging()
    while True:
        try:
            cfg=load_config()
            settings,secrets=cfg["settings"],cfg["secrets"]
            if settings["ntfy"]["enabled"]:
                db_path=Path(settings["daemon"]["database_path"])
                with sqlite3.connect(db_path,isolation_level=None,timeout=10) as db:
                    db.execute("PRAGMA foreign_keys=ON")
                    db.execute("PRAGMA busy_timeout=10000")
                    check_once(db,settings,secrets)
        except Exception as exc:
            event(LOG, logging.ERROR, "MONITOR_UNEXPECTED_FAILURE", subsystem="ntfy", operation="check_once", error_type=type(exc).__name__, retryable=True, exc_info=True)
        wait_for_change(60)

if __name__=="__main__":
    main()
