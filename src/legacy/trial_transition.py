"""Offline SQLite trial-decision transition with durable cancellation intents.

No network calls, filesystem changes, or production schema migrations.
"""
import sqlite3
from trial_decision_gate import TrialState, plan_trial_decision, validate_commit_preconditions, DecisionError


def create_schema(db):
    db.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS trial_state (
      series_id INTEGER PRIMARY KEY, status TEXT NOT NULL,
      identity_bound INTEGER NOT NULL, mapping_approved INTEGER NOT NULL,
      mapping_revision INTEGER NOT NULL, published_prefix INTEGER NOT NULL,
      episode_one_verified INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trial_attempts (
      attempt_id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('ACTIVE','CANCEL_REQUESTED','CANCELLED','FINISHED')),
      FOREIGN KEY(series_id) REFERENCES trial_state(series_id)
    );
    CREATE TABLE IF NOT EXISTS trial_decisions (
      series_id INTEGER PRIMARY KEY, action TEXT NOT NULL,
      mapping_revision INTEGER NOT NULL,
      FOREIGN KEY(series_id) REFERENCES trial_state(series_id)
    );
    CREATE TABLE IF NOT EXISTS cancellation_outbox (
      attempt_id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL,
      state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','ACKNOWLEDGED')),
      FOREIGN KEY(attempt_id) REFERENCES trial_attempts(attempt_id)
    );
    ''')


def snapshot(db, series_id):
    row = db.execute('''SELECT series_id,status,identity_bound,mapping_approved,
          mapping_revision,published_prefix,episode_one_verified
          FROM trial_state WHERE series_id=?''', (series_id,)).fetchone()
    if row is None:
        raise DecisionError('Unknown series')
    attempts = tuple(r[0] for r in db.execute('''
        SELECT attempt_id FROM trial_attempts WHERE series_id=? AND status='ACTIVE'
        ORDER BY attempt_id''', (series_id,)))
    return TrialState(row[0], row[1], bool(row[2]), bool(row[3]), row[4], row[5], bool(row[6]), attempts)


def commit_decision(db, plan):
    """Commit transition and cancellation intents atomically; never call qBittorrent.

    Caller must authenticate the decision separately. SQLite connection must be writable.
    """
    if plan.dry_run is not True or plan.action not in ('KEEP', 'REJECT'):
        raise DecisionError('Invalid plan')
    if db.in_transaction:
        raise DecisionError('Requires a fresh transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        existing = db.execute('SELECT action,mapping_revision FROM trial_decisions WHERE series_id=?',
                              (plan.series_id,)).fetchone()
        if existing:
            if existing == (plan.action, plan.expected_mapping_revision):
                db.commit()
                return 'ALREADY_COMMITTED'
            raise DecisionError('Conflicting decision')
        current = snapshot(db, plan.series_id)
        validate_commit_preconditions(plan, current)
        # Validate all plan fields against freshly computed plan, not just the preconditions.
        canonical = plan_trial_decision(current, plan.action)
        if plan != canonical:
            raise DecisionError('Plan differs from current canonical plan')
        target = 'KEPT' if plan.action == 'KEEP' else 'REJECTED'
        db.execute('UPDATE trial_state SET status=? WHERE series_id=? AND status=?',
                   (target, plan.series_id, 'TRIAL'))
        for attempt_id in plan.cancel_attempts:
            result = db.execute('''UPDATE trial_attempts SET status='CANCEL_REQUESTED'
                 WHERE attempt_id=? AND series_id=? AND status='ACTIVE' ''',
                 (attempt_id, plan.series_id))
            if result.rowcount != 1:
                raise DecisionError('Attempt changed during transition')
            db.execute('INSERT INTO cancellation_outbox(attempt_id,series_id) VALUES(?,?)',
                       (attempt_id, plan.series_id))
        db.execute('INSERT INTO trial_decisions(series_id,action,mapping_revision) VALUES(?,?,?)',
                   (plan.series_id, plan.action, plan.expected_mapping_revision))
        db.commit()
        return 'COMMITTED'
    except BaseException:
        db.rollback()
        raise


def acknowledge_cancellation(db, attempt_id):
    """Offline simulation of an externally confirmed cancellation.

    Production code must validate a real qBittorrent outcome and torrent/attempt identity.
    """
    if type(attempt_id) is not int or attempt_id <= 0:
        raise DecisionError('Invalid attempt ID')
    if db.in_transaction:
        raise DecisionError('Requires a fresh transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT state FROM cancellation_outbox WHERE attempt_id=?',
                         (attempt_id,)).fetchone()
        if not row:
            raise DecisionError('No cancellation intent')
        if row[0] == 'ACKNOWLEDGED':
            db.commit()
            return 'ALREADY_ACKNOWLEDGED'
        updated = db.execute('''UPDATE trial_attempts SET status='CANCELLED'
                             WHERE attempt_id=? AND status='CANCEL_REQUESTED' ''',
                             (attempt_id,))
        if updated.rowcount != 1:
            raise DecisionError('Attempt is not awaiting cancellation')
        db.execute("UPDATE cancellation_outbox SET state='ACKNOWLEDGED' WHERE attempt_id=?", (attempt_id,))
        db.commit()
        return 'ACKNOWLEDGED'
    except BaseException:
        db.rollback()
        raise
