"""Offline cancellation outbox processor. NEVER connects to qBittorrent.

Inventory is supplied by a trusted caller as a snapshot; this prototype only
returns proposed actions and records explicit simulated confirmations.
"""
from dataclasses import dataclass
import re
from trial_decision_gate import DecisionError

_HASH = re.compile(r'(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})\Z')

@dataclass(frozen=True)
class Torrent:
    torrent_hash: str
    attempt_id: int
    state: str  # DOWNLOADING, COMPLETE, PAUSED, MISSING

@dataclass(frozen=True)
class CancellationAction:
    attempt_id: int
    torrent_hash: str
    outcome: str  # WOULD_CANCEL, ALREADY_GONE, NEEDS_RECHECK
    dry_run: bool = True


def create_worker_schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cancellation_targets (
      attempt_id INTEGER PRIMARY KEY REFERENCES trial_attempts(attempt_id),
      torrent_hash TEXT NOT NULL UNIQUE,
      CHECK(length(torrent_hash) IN (40,64))
    );
    CREATE TABLE IF NOT EXISTS cancellation_worker_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      attempt_id INTEGER NOT NULL,
      torrent_hash TEXT NOT NULL,
      outcome TEXT NOT NULL CHECK(outcome IN ('CANCELLED','ALREADY_GONE')),
      UNIQUE(attempt_id)
    );
    ''')


def bind_target(db, attempt_id, torrent_hash):
    """Fixture setup only; production must bind at attempt creation from trusted qB data."""
    if type(attempt_id) is not int or attempt_id <= 0 or not isinstance(torrent_hash, str) or not _HASH.fullmatch(torrent_hash):
        raise DecisionError('Invalid target identity')
    if db.execute('SELECT 1 FROM cancellation_outbox WHERE attempt_id=?', (attempt_id,)).fetchone():
        raise DecisionError('Cannot bind target after cancellation requested')
    db.execute('INSERT INTO cancellation_targets VALUES (?,?)', (attempt_id, torrent_hash.lower()))


def plan_cancellation(db, attempt_id, inventory):
    if type(attempt_id) is not int or attempt_id <= 0:
        raise DecisionError('Invalid attempt ID')
    row = db.execute('''SELECT o.series_id,o.state,a.series_id,a.status,t.torrent_hash
        FROM cancellation_outbox o JOIN trial_attempts a ON a.attempt_id=o.attempt_id
        JOIN cancellation_targets t ON t.attempt_id=o.attempt_id
        WHERE o.attempt_id=?''', (attempt_id,)).fetchone()
    if row is None:
        raise DecisionError('Missing cancellation intent or bound target')
    out_series, out_state, attempt_series, attempt_state, target_hash = row
    if out_series != attempt_series:
        raise DecisionError('Series mismatch')
    if out_state == 'ACKNOWLEDGED':
        return CancellationAction(attempt_id, target_hash, 'ALREADY_GONE')
    if out_state != 'PENDING' or attempt_state != 'CANCEL_REQUESTED':
        raise DecisionError('Cancellation state mismatch')
    if not isinstance(inventory, (tuple, list)) or any(not isinstance(t, Torrent) for t in inventory):
        raise DecisionError('Invalid inventory')
    matches = [t for t in inventory if t.torrent_hash.lower() == target_hash]
    if len(matches) > 1:
        raise DecisionError('Duplicate torrent hash in inventory')
    if not matches:
        return CancellationAction(attempt_id, target_hash, 'ALREADY_GONE')
    item = matches[0]
    if item.attempt_id != attempt_id:
        raise DecisionError('Torrent hash belongs to different attempt')
    if item.state in ('DOWNLOADING','PAUSED','COMPLETE'):
        return CancellationAction(attempt_id, target_hash, 'WOULD_CANCEL')
    raise DecisionError('Unknown torrent state')


def record_simulated_result(db, action, confirmed, inventory):
    """Records a simulated confirmation, never performs a cancellation.

    Caller must recheck inventory immediately before recording; real worker needs
    qBittorrent re-query and an exact-hash cancel with no file deletion.
    """
    if not isinstance(action, CancellationAction) or action.dry_run is not True:
        raise DecisionError('Invalid dry-run action')
    if confirmed not in ('CANCELLED','ALREADY_GONE'):
        raise DecisionError('No confirmed outcome')
    if db.in_transaction:
        raise DecisionError('Requires fresh transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        old = db.execute('SELECT torrent_hash,outcome FROM cancellation_worker_audit WHERE attempt_id=?', (action.attempt_id,)).fetchone()
        if old:
            if old[0] == action.torrent_hash and old[1] == confirmed:
                db.commit()
                return 'ALREADY_RECORDED'
            raise DecisionError('Conflicting confirmation')
        fresh = plan_cancellation(db, action.attempt_id, inventory)
        if fresh != action:
            raise DecisionError('Inventory or target changed')
        if (confirmed == 'ALREADY_GONE') != (fresh.outcome == 'ALREADY_GONE'):
            raise DecisionError('Outcome not supported by inventory')
        db.execute('INSERT INTO cancellation_worker_audit(attempt_id,torrent_hash,outcome) VALUES(?,?,?)',
                   (action.attempt_id, action.torrent_hash, confirmed))
        updated = db.execute("UPDATE trial_attempts SET status='CANCELLED' WHERE attempt_id=? AND status='CANCEL_REQUESTED'", (action.attempt_id,))
        if updated.rowcount != 1:
            raise DecisionError('Attempt no longer cancellable')
        db.execute("UPDATE cancellation_outbox SET state='ACKNOWLEDGED' WHERE attempt_id=? AND state='PENDING'", (action.attempt_id,))
        db.commit()
        return 'RECORDED_SIMULATION'
    except BaseException:
        db.rollback()
        raise
