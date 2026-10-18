"""Offline transactional mapping approval demonstration. NOT a production endpoint.

A signed request authenticates an administrator action, not metadata provenance.
The candidate digest must be pinned by a separate trusted, privileged workflow.
"""
import sqlite3
from approval_authorization import verify_admin_request, AuthorizationError

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE series(id INTEGER PRIMARY KEY);
CREATE TABLE identity_bindings(
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
 UNIQUE(id,series_id));
CREATE TABLE mapping_revisions(
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
 binding_id INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REVOKED')),
 approved_by TEXT, approved_at TEXT,
 FOREIGN KEY(binding_id,series_id) REFERENCES identity_bindings(id,series_id));
CREATE UNIQUE INDEX one_approved_revision ON mapping_revisions(series_id) WHERE status='APPROVED';
CREATE TABLE mapping_entries(
 revision_id INTEGER NOT NULL REFERENCES mapping_revisions(id),
 release_episode INTEGER NOT NULL CHECK(release_episode>0),
 canonical_season INTEGER NOT NULL CHECK(canonical_season=1),
 canonical_episode INTEGER NOT NULL CHECK(canonical_episode BETWEEN 1 AND 6),
 PRIMARY KEY(revision_id,release_episode), UNIQUE(revision_id,canonical_season,canonical_episode));
CREATE TABLE admin_nonces(
 nonce TEXT PRIMARY KEY, action TEXT NOT NULL, actor TEXT NOT NULL,
 revision_id INTEGER NOT NULL REFERENCES mapping_revisions(id), consumed_at TEXT NOT NULL);
CREATE TABLE mapping_audit(
 id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL REFERENCES mapping_revisions(id),
 action TEXT NOT NULL CHECK(action='APPROVE'), actor TEXT NOT NULL,
 nonce TEXT NOT NULL UNIQUE REFERENCES admin_nonces(nonce), occurred_at TEXT NOT NULL);
CREATE TRIGGER immutable_audit_update BEFORE UPDATE ON mapping_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER immutable_audit_delete BEFORE DELETE ON mapping_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER immutable_nonces_update BEFORE UPDATE ON admin_nonces BEGIN SELECT RAISE(ABORT,'nonce immutable'); END;
CREATE TRIGGER immutable_nonces_delete BEFORE DELETE ON admin_nonces BEGIN SELECT RAISE(ABORT,'nonce immutable'); END;
CREATE TRIGGER immutable_entries_update BEFORE UPDATE ON mapping_entries
 WHEN (SELECT status FROM mapping_revisions WHERE id=OLD.revision_id)!='PENDING'
 OR (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id)!='PENDING'
 BEGIN SELECT RAISE(ABORT,'entries locked'); END;
CREATE TRIGGER immutable_entries_delete BEFORE DELETE ON mapping_entries
 WHEN (SELECT status FROM mapping_revisions WHERE id=OLD.revision_id)!='PENDING'
 BEGIN SELECT RAISE(ABORT,'entries locked'); END;
CREATE TRIGGER immutable_entries_insert BEFORE INSERT ON mapping_entries
 WHEN (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id)!='PENDING'
 BEGIN SELECT RAISE(ABORT,'entries locked'); END;
'''


def initialize(db):
    """Only use on a fresh disposable database; never on controller.db."""
    db.executescript(SCHEMA)


def approve_revision(db, *, revision_id, envelope, key, now, trusted_preflight=None):
    """Atomically verify, consume nonce, approve revision, and append audit.

    Caller must independently authenticate/admin-authorize, obtain trusted metadata,
    and pin the candidate digest BEFORE invoking this demonstration. This function
    deliberately does not accept a caller-provided expected target or digest.
    """
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('INVALID_REVISION_ID')
    if db.in_transaction:
        raise ValueError('CALL_REQUIRES_NO_ACTIVE_TRANSACTION')
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('''SELECT r.series_id,r.binding_id,r.candidate_sha256,r.status,b.state
          FROM mapping_revisions r JOIN identity_bindings b
          ON b.id=r.binding_id AND b.series_id=r.series_id WHERE r.id=?''',
          (revision_id,)).fetchone()
        if row is None or row[3] != 'PENDING' or row[4] != 'ACTIVE':
            raise ValueError('NO_ACTIVE_PENDING_REVISION')
        if not db.execute('SELECT 1 FROM mapping_entries WHERE revision_id=?', (revision_id,)).fetchone():
            raise ValueError('EMPTY_MAPPING')
        if trusted_preflight is not None:
            trusted_preflight(db, revision_id, now=now)
        target = {'series_id': row[0], 'binding_id': row[1], 'candidate_sha256': row[2]}
        verified = verify_admin_request(
            envelope=envelope, key=key, expected_action='APPROVE_MAPPING',
            expected_target=target,
            nonce_is_used=lambda nonce: db.execute(
                'SELECT 1 FROM admin_nonces WHERE nonce=?', (nonce,)).fetchone() is not None,
            now=now)
        db.execute('''INSERT INTO admin_nonces(nonce,action,actor,revision_id,consumed_at)
          VALUES (?,?,?,?,CURRENT_TIMESTAMP)''',
          (verified['nonce'], verified['action'], verified['actor'], revision_id))
        updated = db.execute('''UPDATE mapping_revisions
          SET status='APPROVED',approved_by=?,approved_at=CURRENT_TIMESTAMP
          WHERE id=? AND status='PENDING' AND binding_id=? AND candidate_sha256=?''',
          (verified['actor'], revision_id, row[1], row[2]))
        if updated.rowcount != 1:
            raise ValueError('APPROVAL_RACE')
        db.execute('''INSERT INTO mapping_audit(revision_id,action,actor,nonce,occurred_at)
          VALUES (?,'APPROVE',?,?,CURRENT_TIMESTAMP)''',
          (revision_id, verified['actor'], verified['nonce']))
        db.commit()
        return {'revision_id': revision_id, 'status': 'APPROVED'}
    except BaseException:
        db.rollback()
        raise
