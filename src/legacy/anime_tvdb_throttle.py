"""SQLite-coordinated TVDB pacing scoped to the identity worker.

A deferred request does not contact TVDB; callers reschedule instead.
No credentials, bearer tokens or response bodies are persisted.
"""
import contextlib
import contextvars
import datetime
import email.utils
import sqlite3
import time
from pathlib import Path

_SCOPE=contextvars.ContextVar("tvdb_throttle_db",default=None)
NORMAL_GAP=1
ERROR_BASE=10
ERROR_CAP=600

class TVDBDeferred(Exception):
    def __init__(self,reason,retry_after_seconds=0):
        self.retry_after_seconds=max(1,int(retry_after_seconds))
        super().__init__(reason)

@contextlib.contextmanager
def tvdb_scope(path):
    token=_SCOPE.set(Path(path))
    try:
        yield
    finally:
        _SCOPE.reset(token)

def current_scope():
    return _SCOPE.get()

def _db(path):
    db=sqlite3.connect(path,timeout=15,isolation_level=None)
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("""CREATE TABLE IF NOT EXISTS tvdb_http_limit (
      id INTEGER PRIMARY KEY CHECK(id=1),
      next_allowed_at INTEGER NOT NULL,
      failures INTEGER NOT NULL DEFAULT 0)""")
    db.execute("INSERT OR IGNORE INTO tvdb_http_limit VALUES (1,0,0)")
    return db

def reserve_request(path,*,now=None):
    stamp=int(time.time() if now is None else now)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with _db(path) as db:
        db.execute("BEGIN IMMEDIATE")
        next_at=db.execute("SELECT next_allowed_at FROM tvdb_http_limit WHERE id=1").fetchone()[0]
        if next_at>stamp:
            raise TVDBDeferred("TVDB shared request pacing",next_at-stamp)
        db.execute("UPDATE tvdb_http_limit SET next_allowed_at=? WHERE id=1",
                   (stamp+NORMAL_GAP,))

def _retry_after(value,now):
    if value is None:
        return 0
    try:
        return max(0,min(86400,int(value)))
    except (ValueError,TypeError):
        try:
            dt=email.utils.parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt=dt.replace(tzinfo=datetime.timezone.utc)
            return max(0,min(86400,int(dt.timestamp()-now)+1))
        except (TypeError,ValueError,OverflowError):
            return 0

def record_failure(path,status,retry_after,*,now=None):
    if status not in (429,500,502,503,504):
        return
    stamp=int(time.time() if now is None else now)
    with _db(path) as db:
        db.execute("BEGIN IMMEDIATE")
        count=db.execute("SELECT failures FROM tvdb_http_limit WHERE id=1").fetchone()[0]
        wait=max(_retry_after(retry_after,stamp),
                 min(ERROR_CAP,ERROR_BASE*2**min(count,6)))
        db.execute("""UPDATE tvdb_http_limit SET failures=?,
                 next_allowed_at=MAX(next_allowed_at,?) WHERE id=1""",
                 (min(count+1,7),stamp+wait))
