"""Fail-closed fresh-attempt ownership ledger. Offline/disposable DB only.

A claim is NOT proof of exclusive qB ownership. No qB mutation methods exist.
"""
import re
import sqlite3
from pathlib import Path

HASH = re.compile(r'^[0-9a-fA-F]{40}$')

class OwnershipBlocked(RuntimeError):
    pass

def _disposable(db):
    from trial_integration_sprint import assert_disposable
    assert_disposable(db)

def install(db_path, db):
    _disposable(db_path)
    db.execute('''CREATE TABLE IF NOT EXISTS fresh_attempt_ownership (
      attempt_id INTEGER PRIMARY KEY,
      series_id INTEGER NOT NULL,
      season INTEGER NOT NULL CHECK(season=1),
      episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 6),
      generation INTEGER NOT NULL CHECK(generation>0),
      torrent_hash TEXT NOT NULL UNIQUE,
      origin TEXT NOT NULL CHECK(origin='CONTROLLER_CREATED'),
      state TEXT NOT NULL CHECK(state IN ('REGISTERED','REVOKED')),
      UNIQUE(series_id,season,episode,generation))''')

def register(db_path, db, *, attempt_id, series_id, episode, generation, torrent_hash,
             creation_receipt, inventory_before, inventory_after):
    """Register only a new hash with explicit controller creation receipt.

    Caller must serialize its own qB add and all controller cancellation operations.
    Inventory checks are necessary, not sufficient, against external qB writers.
    """
    _disposable(db_path)
    if not all(type(v) is int and v > 0 for v in (attempt_id,series_id,episode,generation)) or episode > 6:
        raise OwnershipBlocked('invalid attempt coordinates')
    if not isinstance(torrent_hash,str) or not HASH.fullmatch(torrent_hash):
        raise OwnershipBlocked('invalid hash')
    h = torrent_hash.lower()
    if not isinstance(creation_receipt,dict) or creation_receipt.get('source') != 'controller-add' or creation_receipt.get('attempt_id') != attempt_id or creation_receipt.get('generation') != generation or creation_receipt.get('hash') != h:
        raise OwnershipBlocked('no matching controller creation receipt')
    if not isinstance(inventory_before,set) or not isinstance(inventory_after,set):
        raise OwnershipBlocked('inventory snapshots required')
    if h in {str(x).lower() for x in inventory_before} or h not in {str(x).lower() for x in inventory_after}:
        raise OwnershipBlocked('hash not newly created')
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT id,series_id,season,episode,torrent_hash FROM download_attempts WHERE id=?',(attempt_id,)).fetchone()
        if not row or row[1:4] != (series_id,1,episode) or str(row[4]).lower()!=h:
            raise OwnershipBlocked('attempt mismatch')
        newer = db.execute('SELECT 1 FROM download_attempts WHERE series_id=? AND season=1 AND episode=? AND id>? LIMIT 1',(series_id,episode,attempt_id)).fetchone()
        if newer:
            raise OwnershipBlocked('superseded attempt')
        db.execute('INSERT INTO fresh_attempt_ownership VALUES (?,?,?,?,?,?,?,?)', (attempt_id,series_id,1,episode,generation,h,'CONTROLLER_CREATED','REGISTERED'))
        db.commit()
    except (sqlite3.IntegrityError,OwnershipBlocked) as exc:
        db.rollback()
        raise OwnershipBlocked(str(exc)) from exc
    except BaseException:
        db.rollback()
        raise

def preflight(db_path, db, *, attempt_id, generation, torrent_hash, inventory_hashes):
    """Read-only fence; does NOT authorize an external deletion by itself."""
    _disposable(db_path)
    if type(attempt_id) is not int or type(generation) is not int or not isinstance(torrent_hash,str) or not HASH.fullmatch(torrent_hash):
        raise OwnershipBlocked('invalid fence inputs')
    h=torrent_hash.lower()
    row=db.execute('SELECT series_id,season,episode,generation,torrent_hash,state FROM fresh_attempt_ownership WHERE attempt_id=?',(attempt_id,)).fetchone()
    if not row or row[3]!=generation or row[4]!=h or row[5]!='REGISTERED':
        raise OwnershipBlocked('missing active ownership record')
    attempt=db.execute('SELECT series_id,season,episode,torrent_hash FROM download_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not attempt or attempt[:3]!=row[:3] or str(attempt[3]).lower()!=h:
        raise OwnershipBlocked('attempt changed')
    if db.execute('SELECT 1 FROM download_attempts WHERE series_id=? AND season=? AND episode=? AND id>? LIMIT 1',(row[0],row[1],row[2],attempt_id)).fetchone():
        raise OwnershipBlocked('newer attempt exists')
    if not isinstance(inventory_hashes,set) or h not in {str(x).lower() for x in inventory_hashes}:
        raise OwnershipBlocked('torrent absent')
    return {'attempt_id':attempt_id,'generation':generation,'torrent_hash':h,'external_mutation_authorized':False}
