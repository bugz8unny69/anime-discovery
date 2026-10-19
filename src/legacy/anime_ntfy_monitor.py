"""Unified-database review reminder scheduler; never mutates acquisition state."""
import sqlite3
import time
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
    # Upgrade older unmatched RECEIVED rows so they can be reviewed too.
    db.execute("""UPDATE notifications SET status='NEEDS_REVIEW'
        WHERE status IN ('RECEIVED','UNTRUSTED') AND NOT EXISTS
        (SELECT 1 FROM episode_dispatch d WHERE d.notification_id=notifications.id)""")
    interval=max(3600,settings["ntfy"]["reminder_hours"]*3600)
    rows=db.execute("""SELECT n.id,n.release_name FROM notifications n
        LEFT JOIN episode_dispatch d ON d.notification_id=n.id
        LEFT JOIN ntfy_delivery sent ON sent.notification_id=n.id
        WHERE d.notification_id IS NULL AND n.status='NEEDS_REVIEW'
          AND (sent.sent_at IS NULL OR sent.sent_at<=?)
        ORDER BY n.id ASC LIMIT 50""",(now-interval,)).fetchall()
    sent=0
    for notification_id,title in rows:
        if sender(settings,secrets,notification_id,title):
            mark_sent(db,notification_id,now=now)
            sent+=1
    return {"sent":sent,"pending":len(rows)}

def main():
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
            LOG.warning("NTFY monitor iteration failed (%s)",type(exc).__name__)
        time.sleep(60)

if __name__=="__main__":
    main()
