"""Production-edge adapters. Importing this module has no side effects.

The qB worker defaults to dry-run and requires an injected authenticated client.
Automatic mapping approval remains disabled until genuine provider adapters exist.
"""
import os
import sqlite3
import stat
from pathlib import Path

ACTIVE = frozenset({'QUEUED', 'DOWNLOADING', 'STALLED'})

class EdgeBlocked(RuntimeError):
    pass


def snapshot_to_disposable(source, destination):
    """Read-only SQLite online backup; never modifies source.

    Explicit paths only. Refuses existing destinations, symlinks, and production
    destination paths. The caller must arrange access to source.
    """
    source, destination = Path(source), Path(destination)
    if not source.is_absolute() or not destination.is_absolute():
        raise EdgeBlocked('absolute paths required')
    if destination.exists() or destination.is_symlink():
        raise EdgeBlocked('destination already exists')
    if str(destination).startswith('/var/lib/anime-discovery/'):
        raise EdgeBlocked('destination inside production data directory')
    if not source.is_file() or source.is_symlink():
        raise EdgeBlocked('source must be a regular, non-symlink database')
    if source.resolve() == destination.resolve():
        raise EdgeBlocked('source and destination must differ')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        src = sqlite3.connect(f'file:{source}?mode=ro', uri=True, timeout=5)
        try:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise EdgeBlocked('snapshot integrity check failed')
                if dst.execute('PRAGMA foreign_key_check').fetchall():
                    raise EdgeBlocked('snapshot foreign key check failed')
            finally:
                dst.close()
        finally:
            src.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def cancellation_preflight(db, *, series_id, attempt_id, torrent_hash, inventory_hashes):
    """Re-read current DB attempt binding; inventory is full qB hash set.

    Never infer attempt generation from qB inventory: qB does not expose it.
    Any re-registration or replacement after this preflight must block execution.
    """
    if type(series_id) is not int or type(attempt_id) is not int or series_id <= 0 or attempt_id <= 0:
        raise EdgeBlocked('invalid IDs')
    if not isinstance(torrent_hash, str) or len(torrent_hash) != 40 or any(c not in '0123456789abcdef' for c in torrent_hash.lower()):
        raise EdgeBlocked('invalid hash')
    if not isinstance(inventory_hashes, (set, frozenset)):
        raise EdgeBlocked('inventory must be a full hash set')
    row = db.execute('''SELECT id, series_id, season, episode, torrent_hash, status
        FROM download_attempts WHERE id=?''', (attempt_id,)).fetchone()
    if row is None or row[1] != series_id or row[4].lower() != torrent_hash.lower() or row[5] not in ACTIVE:
        raise EdgeBlocked('attempt binding or state changed')
    latest = db.execute('''SELECT MAX(id) FROM download_attempts
        WHERE series_id=? AND season=? AND episode=?''', (series_id, row[2], row[3])).fetchone()[0]
    if latest != attempt_id:
        raise EdgeBlocked('newer attempt exists')
    if torrent_hash.lower() not in {x.lower() for x in inventory_hashes}:
        return 'ABSENT'
    return 'ELIGIBLE'


def cancel_once(db, *, series_id, attempt_id, torrent_hash, inventory_provider, remove_torrent,
                enabled=False):
    """Single-process fenced cancellation, disabled by default.

    Holds BEGIN IMMEDIATE across the final inventory refresh and qB request.
    This prevents competing controller writers, NOT external qB clients. Therefore
    live enablement must additionally enforce exclusive ownership of qB hashes.
    remove_torrent(hash, delete_files=False) must be an audited adapter.
    """
    if not enabled:
        return {'status': 'DISABLED', 'delete_files': False}
    if db.in_transaction:
        raise EdgeBlocked('requires dedicated connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        hashes = inventory_provider()
        status = cancellation_preflight(db, series_id=series_id, attempt_id=attempt_id,
                    torrent_hash=torrent_hash, inventory_hashes=hashes)
        if status == 'ABSENT':
            db.execute('COMMIT')
            return {'status': 'ALREADY_ABSENT', 'delete_files': False}
        # The injected adapter MUST use qB /api/v2/torrents/delete with
        # deleteFiles=false, and MUST NOT retry against a different hash.
        remove_torrent(torrent_hash.lower(), delete_files=False)
        db.execute('COMMIT')
        return {'status': 'REMOVE_REQUESTED', 'delete_files': False}
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def automatic_mapping_approval(*args, **kwargs):
    """No fake trust from caller-provided provider flags or metadata."""
    raise EdgeBlocked('authenticated canonical-numbering provider adapters not installed')
