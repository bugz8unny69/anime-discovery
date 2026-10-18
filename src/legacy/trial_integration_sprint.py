"""Offline integration of real controller read paths with an isolated trial decision API.

Not production ready: mapping provenance and qB cancellation are deliberately disabled.
No external effects. Explicit disposable DB path only.
"""
import os
import sqlite3
import secrets
from contextlib import contextmanager
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

PRODUCTION_DB = '/var/lib/anime-discovery/controller.db'
DDL = '''
CREATE TABLE IF NOT EXISTS trial_mapping_gate (
 series_id INTEGER PRIMARY KEY REFERENCES series(id),
 state TEXT NOT NULL CHECK(state IN ('REVIEW_REQUIRED','MANUAL_APPROVED')) DEFAULT 'REVIEW_REQUIRED',
 revision INTEGER NOT NULL DEFAULT 1,
 evidence_digest TEXT NOT NULL DEFAULT '',
 admin_actor TEXT NOT NULL DEFAULT '',
 CHECK(state != 'MANUAL_APPROVED' OR (length(evidence_digest)=64 AND length(admin_actor)>0))
);
CREATE TABLE IF NOT EXISTS trial_decision_gate (
 series_id INTEGER PRIMARY KEY REFERENCES series(id),
 action TEXT NOT NULL CHECK(action IN ('KEEP','REJECT')),
 episode1_attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
 mapping_revision INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trial_cancel_outbox (
 id INTEGER PRIMARY KEY,
 series_id INTEGER NOT NULL REFERENCES series(id),
 attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
 torrent_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','BLOCKED','DONE')),
 delete_files INTEGER NOT NULL DEFAULT 0 CHECK(delete_files=0),
 UNIQUE(series_id,attempt_id)
);
'''

class Decision(BaseModel):
    action: str
    episode1_attempt_id: int = Field(gt=0)


def assert_disposable(path):
    p = Path(path).resolve()
    if p == Path(PRODUCTION_DB).resolve() or not p.is_file() or not p.name.endswith('.db'):
        raise ValueError('Explicit existing disposable .db fixture required')
    # Refuse hardlinked copies of the live DB when accessible.
    if os.path.exists(PRODUCTION_DB) and os.path.samefile(p, PRODUCTION_DB):
        raise ValueError('Production database forbidden')
    return str(p)


def install(db):
    if db.in_transaction:
        raise ValueError('Migration must start outside a transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        for statement in DDL.split(';'):
            if statement.strip():
                db.execute(statement)
        for table, required in {'trial_mapping_gate': {'series_id','state','revision'}, 'trial_decision_gate': {'series_id','action','episode1_attempt_id'}, 'trial_cancel_outbox': {'series_id','attempt_id','torrent_hash','delete_files'}}.items():
            columns = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
            if not required.issubset(columns):
                raise sqlite3.OperationalError('Migration schema collision: ' + table)
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def make_router(*, db_path, decision_token, discovery_token, verify_episode1):
    """verify_episode1(db, sid, attempt_id) must perform fresh, real file checks.

    Injection is restricted to disposable rehearsals. Never mount on live app.
    """
    path = assert_disposable(db_path)
    if not decision_token or not discovery_token or secrets.compare_digest(decision_token, discovery_token):
        raise ValueError('Separate nonempty credentials required')
    router = APIRouter(prefix='/offline-trial')

    def admin_auth(authorization: str | None = Header(default=None)):
        if not authorization or not secrets.compare_digest(authorization, 'Bearer ' + decision_token):
            raise HTTPException(401, 'Separate decision credential required')

    @contextmanager
    def transaction():
        db = sqlite3.connect(path, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    @router.post('/series/{sid}/decision', dependencies=[Depends(admin_auth)])
    def decide(sid: int, body: Decision):
        if body.action not in ('KEEP','REJECT'):
            raise HTTPException(422, 'Invalid action')
        with transaction() as db:
            old = db.execute('SELECT action,episode1_attempt_id FROM trial_decision_gate WHERE series_id=?', (sid,)).fetchone()
            if old:
                if old['action'] == body.action and old['episode1_attempt_id'] == body.episode1_attempt_id:
                    return {'result':'unchanged','dry_run':True}
                raise HTTPException(409, 'Conflicting decision')
            series = db.execute('SELECT status FROM series WHERE id=?', (sid,)).fetchone()
            if not series or series['status'] not in ('ACQUIRING','PENDING_REVIEW'):
                raise HTTPException(409, 'Series ineligible')
            mapping = db.execute('SELECT state,revision FROM trial_mapping_gate WHERE series_id=?', (sid,)).fetchone()
            if not mapping or mapping['state'] != 'MANUAL_APPROVED':
                raise HTTPException(409, 'Mapping not independently approved')
            attempt = db.execute('''SELECT id,status FROM download_attempts
              WHERE id=? AND series_id=? AND season=1 AND episode=1''', (body.episode1_attempt_id,sid)).fetchone()
            if not attempt or attempt['status'] != 'COMPLETED':
                raise HTTPException(409, 'Episode 1 attempt ineligible')
            # Must be backed by staged_episodes and fresh media+stability verification.
            staged = db.execute('''SELECT status,attempt_id,staged_path,imported_path FROM staged_episodes
              WHERE series_id=? AND season=1 AND episode=1''', (sid,)).fetchone()
            if not staged or staged['attempt_id'] != body.episode1_attempt_id or staged['status'] not in ('STAGED','IMPORTED'):
                raise HTTPException(409, 'Episode 1 staging mismatch')
            if verify_episode1(db,sid,body.episode1_attempt_id) is not True:
                raise HTTPException(409, 'Episode 1 not freshly verified')
            db.execute('''INSERT INTO trial_decision_gate(series_id,action,episode1_attempt_id,mapping_revision)
              VALUES(?,?,?,?)''', (sid,body.action,body.episode1_attempt_id,mapping['revision']))
            db.execute('''INSERT INTO trial_cancel_outbox(series_id,attempt_id,torrent_hash)
              SELECT series_id,id,torrent_hash FROM download_attempts WHERE series_id=?
              AND status IN ('QUEUED','DOWNLOADING','STALLED')''',(sid,))
            return {'result':'recorded','action':body.action,'dry_run':True,'cancellation_enabled':False}
    return router


def production_verifier_from_api(controller):
    """Use actual controller's ffprobe, dual-audio and stability checks on current staged file.

    This is a contract helper; NEVER wire into live API until provenance and
    deployment checks are complete. Race-resistant file descriptors still needed.
    """
    def verify(db,sid,attempt_id):
        row = db.execute('''SELECT st.status,st.staged_path,st.imported_path,a.status AS attempt_status
            FROM staged_episodes st JOIN download_attempts a ON a.id=st.attempt_id
            AND a.series_id=st.series_id AND a.season=st.season AND a.episode=st.episode
            WHERE st.series_id=? AND st.season=1 AND st.episode=1 AND st.attempt_id=?''',(sid,attempt_id)).fetchone()
        if not row or row['attempt_status'] != 'COMPLETED':
            return False
        if row['status'] == 'STAGED':
            return (controller.staged_file_check(row['staged_path'],row['attempt_status'])['verified'] is True
                    and controller.check_file_stability(db,sid,1,1,row['staged_path'])['stable'] is True)
        if row['status'] == 'IMPORTED':
            return controller.imported_file_check(row['imported_path'],row['attempt_status'])['verified'] is True
        return False
    return verify
