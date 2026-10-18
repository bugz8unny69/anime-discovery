"""Fail-closed qB add coordinator, DISPOSABLE DATABASES ONLY.

No qB HTTP implementation here. The caller injects an add callback; live mutation
is forbidden by default. The durable PREPARED state is never automatically retried.
"""
import fcntl
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from trial_integration_sprint import assert_disposable

HASH = re.compile(r'^[0-9a-f]{40}$')

class AddBlocked(RuntimeError):
    pass

@contextmanager
def exclusive_lock(path):
    p = Path(path)
    if not p.parent.is_dir() or p.is_symlink():
        raise AddBlocked('invalid lock location')
    with p.open('a+b') as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)

def install(db_path, db):
    assert_disposable(db_path)
    db.execute('''CREATE TABLE IF NOT EXISTS controller_add_journal (
      attempt_id INTEGER PRIMARY KEY,
      series_id INTEGER NOT NULL,
      episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 6),
      generation INTEGER NOT NULL CHECK(generation > 0),
      torrent_hash TEXT NOT NULL UNIQUE,
      state TEXT NOT NULL CHECK(state IN ('PREPARED','CONFIRMED','QUARANTINED')),
      UNIQUE(series_id,episode,generation))''')

def _inventory(inventory):
    rows = inventory()
    if not isinstance(rows, (list, tuple, set)):
        raise AddBlocked('inventory must be a collection')
    hashes = [getattr(row, 'torrent_hash', row) for row in rows]
    if any(not isinstance(h, str) or not HASH.fullmatch(h.lower()) for h in hashes):
        raise AddBlocked('invalid inventory hash')
    hashes = [h.lower() for h in hashes]
    if len(set(hashes)) != len(hashes):
        raise AddBlocked('duplicate inventory hash')
    return set(hashes)

def coordinate(db_path, db, *, attempt_id, series_id, episode, generation,
               torrent_hash, inventory, add, lock_path, allow_external_add=False):
    """Journal intent before add. Never retry uncertain adds or auto-delete.

    Caller must control all other writers for true exclusive ownership. A confirmed
    journal is NOT sufficient to enable cancellation.
    """
    assert_disposable(db_path)
    if not allow_external_add:
        raise AddBlocked('external add disabled')
    if any(type(x) is not int or x <= 0 for x in (attempt_id, series_id, episode, generation)) or episode > 6:
        raise AddBlocked('invalid coordinates')
    if not isinstance(torrent_hash, str) or not HASH.fullmatch(torrent_hash.lower()):
        raise AddBlocked('invalid torrent hash')
    h = torrent_hash.lower()
    with exclusive_lock(lock_path):
        before = _inventory(inventory)
        if h in before:
            raise AddBlocked('torrent already exists; never adopt')
        try:
            db.execute('BEGIN IMMEDIATE')
            attempt = db.execute('SELECT series_id,season,episode,torrent_hash FROM download_attempts WHERE id=?', (attempt_id,)).fetchone()
            if not attempt or attempt[:3] != (series_id,1,episode) or str(attempt[3]).lower() != h:
                raise AddBlocked('download attempt mismatch')
            if db.execute('SELECT 1 FROM download_attempts WHERE series_id=? AND season=1 AND episode=? AND id>? LIMIT 1', (series_id,episode,attempt_id)).fetchone():
                raise AddBlocked('superseded attempt')
            if db.execute('SELECT 1 FROM controller_add_journal WHERE series_id=? AND episode=? AND generation>=? LIMIT 1', (series_id,episode,generation)).fetchone():
                raise AddBlocked('generation already used or superseded')
            db.execute('INSERT INTO controller_add_journal VALUES (?,?,?,?,?,?)', (attempt_id,series_id,episode,generation,h,'PREPARED'))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        try:
            # This callback may have committed remotely before raising. Never retry it.
            result = add(h)
            after = _inventory(inventory)
            if result is not True or h not in after or not before.issubset(after):
                raise AddBlocked('add response/inventory ambiguous')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT state FROM controller_add_journal WHERE attempt_id=?', (attempt_id,)).fetchone() != ('PREPARED',):
                raise AddBlocked('journal changed during add')
            db.execute("UPDATE controller_add_journal SET state='CONFIRMED' WHERE attempt_id=?", (attempt_id,))
            db.commit()
            return {'attempt_id':attempt_id, 'generation':generation, 'torrent_hash':h,
                    'state':'CONFIRMED', 'cancellation_authorized':False}
        except BaseException as exc:
            db.rollback()
            # If process dies, PREPARED persists. On caught failures, quarantine.
            try:
                db.execute("UPDATE controller_add_journal SET state='QUARANTINED' WHERE attempt_id=? AND state='PREPARED'", (attempt_id,))
                db.commit()
            except sqlite3.Error:
                pass
            raise AddBlocked('add outcome uncertain; manual reconciliation required') from exc

def journal_summary(db_path, db):
    assert_disposable(db_path)
    return dict(db.execute('SELECT state,COUNT(*) FROM controller_add_journal GROUP BY state').fetchall())
