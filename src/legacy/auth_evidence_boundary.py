"""2X-AE: offline-only administrative boundary rehearsal.

Only authenticated revocation is implemented. Mapping approval deliberately
fails closed until a real trusted metadata verifier is integrated. Never use
this module as a production HTTP endpoint.
"""
import sqlite3
from approval_authorization import verify_admin_request, AuthorizationError
from integration_transaction_rehearsal import require_memory, ContractError


def install(db):
    require_memory(db)
    db.executescript('''
    CREATE TABLE admin_nonces_v3 (
      nonce TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
      mapping_id INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE admin_events_v3 (
      id INTEGER PRIMARY KEY, nonce TEXT NOT NULL UNIQUE REFERENCES admin_nonces_v3(nonce),
      mapping_id INTEGER NOT NULL REFERENCES mapping_drafts_v2(id),
      event TEXT NOT NULL CHECK(event='REVOKED'), actor TEXT NOT NULL
    );
    CREATE TRIGGER admin_nonce_no_update BEFORE UPDATE ON admin_nonces_v3
    BEGIN SELECT RAISE(ABORT,'immutable nonce'); END;
    CREATE TRIGGER admin_nonce_no_delete BEFORE DELETE ON admin_nonces_v3
    BEGIN SELECT RAISE(ABORT,'immutable nonce'); END;
    CREATE TRIGGER admin_event_no_update BEFORE UPDATE ON admin_events_v3
    BEGIN SELECT RAISE(ABORT,'immutable event'); END;
    CREATE TRIGGER admin_event_no_delete BEFORE DELETE ON admin_events_v3
    BEGIN SELECT RAISE(ABORT,'immutable event'); END;
    ''')


def approve_mapping(*args, **kwargs):
    """No self-declared evidence or authorization flag can enable approval."""
    raise ContractError('PRODUCTION_TRUSTED_METADATA_GATEWAY_NOT_IMPLEMENTED')


def revoke_authenticated(db, *, draft_id, envelope, admin_key, now, fail_at=None):
    """Offline atomic nonce + revocation, using the existing HMAC verifier.

    Existing signing target format is reused; candidate_sha256 is a binding
    to the mapping's evidence digest, not proof the digest is trusted.
    """
    require_memory(db)
    if db.in_transaction:
        raise ContractError('active transaction')
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT d.series_id,d.binding_id,d.evidence_digest,d.state
                            FROM mapping_drafts_v2 d WHERE d.id=?''', (draft_id,)).fetchone()
        if not row or row[3] != 'APPROVED':
            raise ContractError('mapping not approved')
        target = {'series_id': row[0], 'binding_id': row[1], 'candidate_sha256': row[2]}
        verified = verify_admin_request(
            envelope=envelope, key=admin_key, expected_action='REVOKE_MAPPING',
            expected_target=target,
            nonce_is_used=lambda nonce: db.execute(
                'SELECT 1 FROM admin_nonces_v3 WHERE nonce=?', (nonce,)).fetchone() is not None,
            now=now,
        )
        db.execute('INSERT INTO admin_nonces_v3(nonce,actor,action,mapping_id) VALUES(?,?,?,?)',
                   (verified['nonce'],verified['actor'],'REVOKE_MAPPING',draft_id))
        if fail_at == 'nonce':
            raise RuntimeError('injected nonce failure')
        db.execute("UPDATE mapping_drafts_v2 SET state='REVOKED' WHERE id=?",(draft_id,))
        if fail_at == 'state':
            raise RuntimeError('injected state failure')
        db.execute("INSERT INTO mapping_lifecycle_events_v2(draft_id,event,actor) VALUES(?,'REVOKED',?)",
                   (draft_id,verified['actor']))
        db.execute("INSERT INTO admin_events_v3(nonce,mapping_id,event,actor) VALUES(?,?,'REVOKED',?)",
                   (verified['nonce'],draft_id,verified['actor']))
        if fail_at == 'audit':
            raise RuntimeError('injected audit failure')
        db.execute('COMMIT')
        return {'mapping_id': draft_id, 'state': 'REVOKED'}
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
