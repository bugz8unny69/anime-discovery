"""Offline-only FastAPI trial decision rehearsal. Never mount in production."""
import os
import secrets
import sqlite3
from contextlib import contextmanager, closing
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel

SCHEMA = '''
CREATE TABLE trials(series_id INTEGER PRIMARY KEY, mapping_state TEXT NOT NULL, episode1_verified INTEGER NOT NULL DEFAULT 0, current_attempt_id INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'ACQUIRING');
CREATE TABLE decisions(series_id INTEGER PRIMARY KEY REFERENCES trials(series_id), action TEXT NOT NULL, attempt_id INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE cancellation_outbox(id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES trials(series_id), attempt_id INTEGER NOT NULL, torrent_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING', UNIQUE(series_id, attempt_id));
CREATE TABLE attempts(id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES trials(series_id), torrent_hash TEXT NOT NULL, status TEXT NOT NULL);
'''

class Decision(BaseModel):
    action: str
    attempt_id: int


def create_app(db_path, *, decision_token, discovery_token):
    if not db_path or db_path == '/var/lib/anime-discovery/controller.db':
        raise ValueError('Production database forbidden')
    if not decision_token or not discovery_token or secrets.compare_digest(decision_token, discovery_token):
        raise ValueError('Decision and discovery credentials must differ')
    if not os.path.exists(db_path):
        raise ValueError('Disposable database must be explicitly initialized')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(authorization: str | None = Header(None)):
        expected = 'Bearer ' + decision_token
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, 'Decision credential required')

    @contextmanager
    def transaction():
        db = sqlite3.connect(db_path, isolation_level=None, timeout=5)
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

    @app.post('/trial-rehearsal/series/{sid}/decision', dependencies=[Depends(authenticate)])
    def decide(sid: int, body: Decision):
        if body.action not in ('KEEP', 'REJECT'):
            raise HTTPException(422, 'Invalid action')
        with transaction() as db:
            trial = db.execute('SELECT * FROM trials WHERE series_id=?', (sid,)).fetchone()
            if trial is None:
                raise HTTPException(404, 'Trial not found')
            prior = db.execute('SELECT * FROM decisions WHERE series_id=?', (sid,)).fetchone()
            if prior:
                if prior['action'] == body.action and prior['attempt_id'] == body.attempt_id:
                    return {'result': 'unchanged', 'action': body.action, 'dry_run': True}
                raise HTTPException(409, 'Conflicting or stale decision')
            if trial['state'] != 'ACQUIRING' or trial['mapping_state'] != 'APPROVED' or trial['episode1_verified'] != 1:
                raise HTTPException(409, 'Trial not eligible')
            if trial['current_attempt_id'] != body.attempt_id:
                raise HTTPException(409, 'Stale attempt')
            attempt = db.execute('SELECT * FROM attempts WHERE id=? AND series_id=?', (body.attempt_id, sid)).fetchone()
            if not attempt or attempt['status'] != 'COMPLETED':
                raise HTTPException(409, 'Episode 1 attempt not complete')
            db.execute('INSERT INTO decisions(series_id,action,attempt_id) VALUES(?,?,?)', (sid,body.action,body.attempt_id))
            db.execute("UPDATE trials SET state='DECIDED' WHERE series_id=?", (sid,))
            for a in db.execute("SELECT id,torrent_hash FROM attempts WHERE series_id=? AND status IN ('QUEUED','DOWNLOADING','STALLED')", (sid,)).fetchall():
                db.execute('INSERT INTO cancellation_outbox(series_id,attempt_id,torrent_hash) VALUES(?,?,?)', (sid,a['id'],a['torrent_hash']))
            return {'result': 'recorded', 'action': body.action, 'dry_run': True}
    return app


def initialize_disposable(db_path):
    if os.path.exists(db_path) or db_path == '/var/lib/anime-discovery/controller.db':
        raise ValueError('Refuse existing or production database')
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript(SCHEMA)
