"""Phase 2X-AM: offline, synthetic evidence and cancellation fencing rehearsal.

Not a production verifier, metadata attestor, or qBittorrent worker.
"""
import hashlib
import json
import sqlite3


class GateError(ValueError):
    pass


def install(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS am_trials(series_id INTEGER PRIMARY KEY, mapping_state TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'ACQUIRING', current_episode1_attempt INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS am_attempts(id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL,
      episode INTEGER NOT NULL, torrent_hash TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
      status TEXT NOT NULL, FOREIGN KEY(series_id) REFERENCES am_trials(series_id));
    CREATE TABLE IF NOT EXISTS am_evidence(attempt_id INTEGER PRIMARY KEY,
      fingerprint TEXT NOT NULL, staged_path TEXT NOT NULL, size_bytes INTEGER NOT NULL,
      mtime_ns INTEGER NOT NULL, stable INTEGER NOT NULL, media_ok INTEGER NOT NULL,
      dual_audio_ok INTEGER NOT NULL, synthetic INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(attempt_id) REFERENCES am_attempts(id));
    CREATE TABLE IF NOT EXISTS am_decisions(series_id INTEGER PRIMARY KEY, action TEXT NOT NULL,
      attempt_id INTEGER NOT NULL, evidence_fingerprint TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS am_outbox(id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL,
      attempt_id INTEGER NOT NULL, torrent_hash TEXT NOT NULL, generation INTEGER NOT NULL,
      state TEXT NOT NULL DEFAULT 'PENDING', UNIQUE(series_id,attempt_id,generation));
    ''')


def seed(db, *, series_id=1, attempt_id=11):
    db.execute("INSERT INTO am_trials VALUES(?, 'APPROVED', 'ACQUIRING', ?)", (series_id, attempt_id))
    db.execute("INSERT INTO am_attempts VALUES(?,?,?,?,?,?)", (attempt_id,series_id,1,'a'*40,1,'COMPLETED'))
    db.execute("INSERT INTO am_attempts VALUES(?,?,?,?,?,?)", (attempt_id+1,series_id,2,'b'*40,1,'DOWNLOADING'))
    db.commit()


def fingerprint(path, size, mtime, attempt_id):
    payload = json.dumps([path,size,mtime,attempt_id], separators=(',',':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def record_synthetic_evidence(db, attempt_id, *, path='/synthetic/episode1.mkv',
                              size=100_000_000, mtime=1234, stable=True,
                              media_ok=True, dual_audio_ok=True):
    if not path.startswith('/synthetic/') or size <= 0 or mtime < 0:
        raise GateError('Synthetic fixture path or stat invalid')
    digest = fingerprint(path,size,mtime,attempt_id)
    db.execute('''INSERT INTO am_evidence VALUES(?,?,?,?,?,?,?,?,1)
      ON CONFLICT(attempt_id) DO UPDATE SET fingerprint=excluded.fingerprint,
      staged_path=excluded.staged_path,size_bytes=excluded.size_bytes,
      mtime_ns=excluded.mtime_ns,stable=excluded.stable,
      media_ok=excluded.media_ok,dual_audio_ok=excluded.dual_audio_ok''',
      (attempt_id,digest,path,size,mtime,int(stable),int(media_ok),int(dual_audio_ok)))
    db.commit()
    return digest


def decide(db, series_id, action, attempt_id, *, observed_path, observed_size, observed_mtime):
    """Atomic synthetic decision and outbox. Caller observations never establish real trust."""
    if action not in ('KEEP','REJECT'):
        raise GateError('Invalid action')
    if db.in_transaction:
        raise GateError('Requires transaction-free connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        prior = db.execute('SELECT * FROM am_decisions WHERE series_id=?',(series_id,)).fetchone()
        if prior:
            if prior[1] == action and prior[2] == attempt_id:
                db.execute('COMMIT')
                return 'UNCHANGED'
            raise GateError('Conflicting decision')
        trial = db.execute('SELECT * FROM am_trials WHERE series_id=?',(series_id,)).fetchone()
        if not trial or trial[1] != 'APPROVED' or trial[2] != 'ACQUIRING' or trial[3] != attempt_id:
            raise GateError('Trial/mapping/attempt not eligible')
        attempt = db.execute('SELECT * FROM am_attempts WHERE id=? AND series_id=? AND episode=1',
                             (attempt_id,series_id)).fetchone()
        if not attempt or attempt[5] != 'COMPLETED':
            raise GateError('Episode 1 attempt not complete')
        evidence = db.execute('SELECT * FROM am_evidence WHERE attempt_id=?',(attempt_id,)).fetchone()
        expected = fingerprint(observed_path,observed_size,observed_mtime,attempt_id)
        if (not evidence or evidence[1] != expected or not all(evidence[i] == 1 for i in (5,6,7,8))):
            raise GateError('Evidence absent, changed, or unverified')
        db.execute('INSERT INTO am_decisions VALUES(?,?,?,?)',(series_id,action,attempt_id,expected))
        db.execute("UPDATE am_trials SET state='DECIDED' WHERE series_id=?",(series_id,))
        db.execute('''INSERT INTO am_outbox(series_id,attempt_id,torrent_hash,generation)
          SELECT series_id,id,torrent_hash,generation FROM am_attempts
          WHERE series_id=? AND status IN ('QUEUED','DOWNLOADING','STALLED')''',(series_id,))
        db.execute('COMMIT')
        return 'RECORDED_SIMULATION_ONLY'
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def cancellation_preflight(db, outbox_id, *, observed_hash, observed_generation,
                           observed_attempt_id, present):
    """No network access or side effects; returns eligibility only."""
    job = db.execute('SELECT * FROM am_outbox WHERE id=?',(outbox_id,)).fetchone()
    if not job or job[5] != 'PENDING':
        return 'BLOCKED'
    attempt = db.execute('SELECT * FROM am_attempts WHERE id=?',(job[2],)).fetchone()
    if not attempt or attempt[1] != job[1] or attempt[3] != job[3] or attempt[4] != job[4]:
        return 'BLOCKED'
    if (observed_hash != job[3] or observed_generation != job[4]
            or observed_attempt_id != job[2]):
        return 'BLOCKED'
    return 'WOULD_REQUEST_REMOVE_WITH_DELETE_FILES_FALSE' if present else 'ALREADY_ABSENT_SIMULATION'
