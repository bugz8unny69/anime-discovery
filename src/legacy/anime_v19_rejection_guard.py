"""Fail-closed, narrowly scoped rejection guard for the Episode 2 pilot."""
import sqlite3
from pathlib import Path

PILOT_HASH = '175d53091888f5cd7e04f1bc6458034f0018e787'
STATE = Path('/var/lib/anime-discovery/v18-episode2-trial.db')

def blocked(info_hash, state=STATE):
    if info_hash.lower() != PILOT_HASH:
        return False
    # For the protected pilot, missing/corrupt history cannot be interpreted as permission.
    if not state.is_file() or state.is_symlink():
        raise RuntimeError('PILOT_REJECTION_STATE_UNAVAILABLE')
    try:
        with sqlite3.connect(f'file:{state}?mode=ro', uri=True, timeout=5) as db:
            row = db.execute('SELECT action FROM trial_events WHERE torrent_hash=? ORDER BY id DESC LIMIT 1', (PILOT_HASH,)).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError('PILOT_REJECTION_STATE_UNAVAILABLE') from exc
    if row is None:
        raise RuntimeError('PILOT_REJECTION_STATE_UNAVAILABLE')
    return row[0] == 'REJECTED'
