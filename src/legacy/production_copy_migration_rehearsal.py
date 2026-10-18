"""Phase 2X-AN. Offline migration rehearsal. NEVER opens the live controller DB.

Input must be an explicitly supplied disposable SQLite copy. No CLI flag can
point this tool at the controller's production DB path.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

PRODUCTION = Path('/var/lib/anime-discovery/controller.db')
REQUIRED = {'series','episodes','download_attempts','staged_episodes','file_observations'}
DDL = '''
CREATE TABLE an_trial_decisions (
 series_id INTEGER PRIMARY KEY REFERENCES series(id),
 action TEXT NOT NULL CHECK(action IN ('KEEP','REJECT')),
 attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
 evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
 decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE an_cancellation_outbox (
 id INTEGER PRIMARY KEY,
 series_id INTEGER NOT NULL REFERENCES an_trial_decisions(series_id),
 attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
 torrent_hash TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation>=0),
 state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','CLAIMED','DONE','BLOCKED')),
 UNIQUE(series_id,attempt_id,generation)
);
CREATE TABLE an_migration_journal (
 version INTEGER PRIMARY KEY CHECK(version=1),
 installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''
NEW = {'an_trial_decisions','an_cancellation_outbox','an_migration_journal'}

class RehearsalError(ValueError):
    pass

def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

def snapshot(db):
    """Logical snapshot of existing tables, excluding migration-owned objects."""
    out = {}
    for name in sorted(REQUIRED):
        if name not in tables(db):
            raise RehearsalError('Missing expected base table: '+name)
        cols = [r[1] for r in db.execute('PRAGMA table_info("'+name+'")')]
        rows = db.execute('SELECT * FROM "'+name+'"').fetchall()
        serialized = sorted((json.dumps(tuple(row), sort_keys=True, default=str) for row in rows))
        out[name] = {'columns':cols,'count':len(rows),'digest':hashlib.sha256('\n'.join(serialized).encode()).hexdigest()}
    return out

def integrity(db):
    return db.execute('PRAGMA quick_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall()

def migrate(db, *, fail_at=None):
    """Apply within a SAVEPOINT so injected failures roll back all DDL."""
    if not REQUIRED.issubset(tables(db)):
        raise RehearsalError('Base schema mismatch')
    if NEW.intersection(tables(db)) and not NEW.issubset(tables(db)):
        raise RehearsalError('Partial migration detected')
    if NEW.issubset(tables(db)):
        if db.execute('SELECT COUNT(*) FROM an_migration_journal WHERE version=1').fetchone()[0] != 1:
            raise RehearsalError('Migration journal missing')
        return 'ALREADY_APPLIED'
    db.execute('SAVEPOINT an_migration')
    try:
        for idx, statement in enumerate(DDL.split(';')):
            if not statement.strip():
                continue
            db.execute(statement)
            if fail_at == idx:
                raise RehearsalError('Injected failure')
        db.execute('INSERT INTO an_migration_journal(version) VALUES(1)')
        db.execute('RELEASE SAVEPOINT an_migration')
        return 'APPLIED'
    except BaseException:
        db.execute('ROLLBACK TO SAVEPOINT an_migration')
        db.execute('RELEASE SAVEPOINT an_migration')
        raise

def rollback(db):
    """Rollback is permitted only if migration tables contain no business records."""
    if not NEW.issubset(tables(db)):
        raise RehearsalError('Migration not fully present')
    for name in ('an_trial_decisions','an_cancellation_outbox'):
        if db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]:
            raise RehearsalError('Refusing destructive rollback: '+name+' contains records')
    db.execute('SAVEPOINT an_rollback')
    try:
        for name in ('an_cancellation_outbox','an_trial_decisions','an_migration_journal'):
            db.execute('DROP TABLE '+name)
        db.execute('RELEASE SAVEPOINT an_rollback')
    except BaseException:
        db.execute('ROLLBACK TO SAVEPOINT an_rollback')
        db.execute('RELEASE SAVEPOINT an_rollback')
        raise

def rehearse(db):
    db.execute('PRAGMA foreign_keys=ON')
    before = snapshot(db)
    if not integrity(db):
        raise RehearsalError('Pre-migration integrity failed')
    result = migrate(db)
    if migrate(db) != 'ALREADY_APPLIED':
        raise RehearsalError('Not idempotent')
    if snapshot(db) != before or not integrity(db):
        raise RehearsalError('Migration changed existing records or integrity')
    rollback(db)
    if snapshot(db) != before or NEW.intersection(tables(db)) or not integrity(db):
        raise RehearsalError('Rollback did not restore original state')
    return {'phase':'2X-AN','migration':result,'idempotent':True,'rollback_verified':True,
            'existing_data_unchanged':True,'integrity_ok':True,'production_ready':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--copy',required=True,help='Explicit disposable SQLite database copy')
    p.add_argument('--output',help='Optional JSON report')
    a=p.parse_args()
    path=Path(a.copy).expanduser().resolve(strict=True)
    if path == PRODUCTION or path.name == 'controller.db' or not path.is_file():
        p.error('Refusing production or ambiguously named database path')
    # Open read-only, then backup to memory; no writes to the supplied copy.
    src=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
    try:
        db=sqlite3.connect(':memory:')
        src.backup(db)
    finally:
        src.close()
    try:
        result=rehearse(db)
    finally:
        db.close()
    output=json.dumps(result,indent=2,sort_keys=True)
    if a.output:
        Path(a.output).write_text(output+'\n')
    print(output)

if __name__=='__main__':
    main()
