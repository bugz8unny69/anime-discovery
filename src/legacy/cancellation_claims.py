"""Offline SQLite cancellation-outbox lease prototype. No external I/O.

Use a dedicated SQLite connection; call install() only on disposable databases.
The caller owns authentication and must verify actual qBittorrent outcomes.
"""
import sqlite3
import time
import uuid


class ClaimError(ValueError):
    pass


def install(db):
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cancellation_jobs (
      id INTEGER PRIMARY KEY,
      series_id INTEGER NOT NULL CHECK(series_id > 0),
      attempt_id INTEGER NOT NULL CHECK(attempt_id > 0),
      torrent_hash TEXT NOT NULL CHECK(length(torrent_hash) IN (40,64)),
      state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','LEASED','DONE','BLOCKED')),
      generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
      lease_token TEXT,
      lease_until INTEGER,
      tries INTEGER NOT NULL DEFAULT 0 CHECK(tries >= 0),
      next_retry_at INTEGER NOT NULL DEFAULT 0,
      outcome TEXT,
      UNIQUE(attempt_id, torrent_hash),
      CHECK((state='LEASED' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
         OR (state!='LEASED' AND lease_token IS NULL AND lease_until IS NULL))
    );
    CREATE TABLE IF NOT EXISTS cancellation_job_events (
      id INTEGER PRIMARY KEY,
      job_id INTEGER NOT NULL REFERENCES cancellation_jobs(id),
      generation INTEGER NOT NULL,
      event TEXT NOT NULL,
      occurred_at INTEGER NOT NULL
    );
    CREATE TRIGGER IF NOT EXISTS cancellation_events_no_update
      BEFORE UPDATE ON cancellation_job_events BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
    CREATE TRIGGER IF NOT EXISTS cancellation_events_no_delete
      BEFORE DELETE ON cancellation_job_events BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
    ''')


def _now(value):
    n = int(time.time()) if value is None else value
    if type(n) is not int or n < 0:
        raise ClaimError('invalid timestamp')
    return n


def _transaction(db, fn):
    db.execute('BEGIN IMMEDIATE')
    try:
        result = fn()
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def enqueue(db, series_id, attempt_id, torrent_hash):
    if any(type(v) is not int or v <= 0 for v in (series_id, attempt_id)):
        raise ClaimError('invalid IDs')
    if not isinstance(torrent_hash, str) or len(torrent_hash) not in (40,64) or any(c not in '0123456789abcdef' for c in torrent_hash):
        raise ClaimError('invalid lowercase torrent hash')
    def op():
        row = db.execute('SELECT id,series_id FROM cancellation_jobs WHERE attempt_id=? AND torrent_hash=?', (attempt_id,torrent_hash)).fetchone()
        if row:
            if row[1] != series_id:
                raise ClaimError('attempt collision')
            return row[0]
        cur = db.execute('INSERT INTO cancellation_jobs(series_id,attempt_id,torrent_hash) VALUES(?,?,?)',(series_id,attempt_id,torrent_hash))
        return cur.lastrowid
    return _transaction(db,op)


def claim(db, *, now=None, lease_seconds=60, max_tries=5):
    n = _now(now)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise ClaimError('invalid lease duration')
    if type(max_tries) is not int or max_tries < 1:
        raise ClaimError('invalid max tries')
    def op():
        row = db.execute('''SELECT id,generation,tries FROM cancellation_jobs
          WHERE ((state='PENDING' AND next_retry_at<=?) OR (state='LEASED' AND lease_until<=?))
          AND tries<? ORDER BY id LIMIT 1''',(n,n,max_tries)).fetchone()
        if row is None:
            return None
        jid,gen,tries = row
        token=uuid.uuid4().hex
        db.execute('''UPDATE cancellation_jobs SET state='LEASED',generation=?,tries=?,lease_token=?,lease_until=?,outcome=NULL
          WHERE id=?''',(gen+1,tries+1,token,n+lease_seconds,jid))
        db.execute('INSERT INTO cancellation_job_events(job_id,generation,event,occurred_at) VALUES(?,?,?,?)',(jid,gen+1,'CLAIMED',n))
        return {'job_id':jid,'generation':gen+1,'lease_token':token,'lease_until':n+lease_seconds}
    return _transaction(db,op)


def finish(db, claim_record, outcome, *, now=None, retry_seconds=60):
    n=_now(now)
    if outcome not in ('CONFIRMED_ABSENT','RETRY','BLOCKED'):
        raise ClaimError('invalid outcome')
    if type(retry_seconds) is not int or not 1 <= retry_seconds <= 86400:
        raise ClaimError('invalid retry delay')
    try:
        jid=claim_record['job_id']; gen=claim_record['generation']; token=claim_record['lease_token']
    except (KeyError,TypeError):
        raise ClaimError('invalid claim') from None
    if any(type(x) is not int or x <= 0 for x in (jid,gen)) or not isinstance(token,str) or len(token)!=32:
        raise ClaimError('invalid claim')
    def op():
        row=db.execute('SELECT state,generation,lease_token,lease_until FROM cancellation_jobs WHERE id=?',(jid,)).fetchone()
        if row is None or row[0]!='LEASED' or row[1]!=gen or row[2]!=token or row[3]<=n:
            raise ClaimError('stale or expired lease')
        state={'CONFIRMED_ABSENT':'DONE','RETRY':'PENDING','BLOCKED':'BLOCKED'}[outcome]
        db.execute('''UPDATE cancellation_jobs SET state=?,lease_token=NULL,lease_until=NULL,
          next_retry_at=?,outcome=? WHERE id=?''',(state,n+retry_seconds if state=='PENDING' else 0,outcome,jid))
        db.execute('INSERT INTO cancellation_job_events(job_id,generation,event,occurred_at) VALUES(?,?,?,?)',(jid,gen,outcome,n))
        return state
    return _transaction(db,op)


def inspect(db, job_id):
    return db.execute('SELECT state,generation,tries,lease_until,next_retry_at,outcome FROM cancellation_jobs WHERE id=?',(job_id,)).fetchone()
