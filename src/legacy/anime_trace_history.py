"""Durable, bounded diagnostic history using the existing SQLite database.

Never store raw release payloads, URLs, credentials, or exception messages.
"""
import logging
import re
import time
from anime_diagnostics import event

LOG = logging.getLogger(__name__)
_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")

def for_notification(notification_id):
    if type(notification_id) is not int or notification_id <= 0:
        raise ValueError("Invalid notification id")
    return "AD-" + str(notification_id)

def trace_for_job(db, job):
    """Use notification lineage when available, otherwise a stable job-root ID."""
    kind=job["kind"]
    key=job["subject_key"]
    nid=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_job_lineage'").fetchone():
        row=db.execute("SELECT notification_id FROM anime_job_lineage WHERE job_id=?",
                       (job["id"],)).fetchone()
        if row and row[0]:
            nid=row[0]
    if nid is None and kind in ("claimed_acquisition","verified_batch_acquisition") and str(key).isdigit():
        nid=int(key)
    if nid is None and kind=="identity_resolution" and str(key).startswith("notification:"):
        raw=str(key).split(":",1)[1]
        if raw.isdigit():
            nid=int(raw)
    if nid is not None and db.execute(
            "SELECT 1 FROM notifications WHERE id=?",(nid,)).fetchone():
        return for_notification(nid),nid
    return "AJ-"+str(job["id"]),None

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_trace_events (
        id INTEGER PRIMARY KEY,
        trace_id TEXT NOT NULL,
        job_id INTEGER,
        notification_id INTEGER,
        recorded_at REAL NOT NULL,
        event_name TEXT NOT NULL,
        stage TEXT,
        hook TEXT,
        outcome TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS anime_trace_lookup ON anime_trace_events(trace_id,id)")

def record(db, trace_id, name, *, job_id=None, notification_id=None,
           stage=None, hook=None, outcome=None):
    for item in (trace_id,name,stage,hook,outcome):
        if item is not None and (not isinstance(item,str) or not _TOKEN.fullmatch(item)):
            raise ValueError("Unsafe trace event field")
    for item in (job_id,notification_id):
        if item is not None and (type(item) is not int or item<=0):
            raise ValueError("Invalid event reference")
    ensure_schema(db)
    db.execute("""INSERT INTO anime_trace_events
        (trace_id,job_id,notification_id,recorded_at,event_name,stage,hook,outcome)
        VALUES (?,?,?,?,?,?,?,?)""",
        (trace_id,job_id,notification_id,time.time(),name,stage,hook,outcome))
    event(LOG,logging.INFO,name,trace_id=trace_id,job_id=job_id,
          notification_id=notification_id,stage=stage,hook=hook,outcome=outcome)

def history(db, trace_id, *, limit=250):
    if not isinstance(trace_id,str) or not _TOKEN.fullmatch(trace_id):
        raise ValueError("Invalid trace id")
    if type(limit) is not int or not 1<=limit<=500:
        raise ValueError("Invalid history limit")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_trace_events'").fetchone():
        return []
    rows=db.execute("""SELECT id,job_id,notification_id,recorded_at,event_name,
        stage,hook,outcome FROM anime_trace_events WHERE trace_id=?
        ORDER BY id DESC LIMIT ?""",(trace_id,limit)).fetchall()
    return [dict(zip(("id","job_id","notification_id","recorded_at",
                      "event","stage","hook","outcome"),row)) for row in reversed(rows)]
