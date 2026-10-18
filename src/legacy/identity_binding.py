"""Offline identity-binding storage prototype. NOT an authentication boundary.

Only a future privileged controller component may call bind/revoke. Do not expose
these functions through the discovery-token API or accept IDs from RSS payloads.
"""
import sqlite3
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def initialize(db):
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE series (
      id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
      title TEXT NOT NULL, UNIQUE(source, external_id)
    );
    CREATE TABLE identity_bindings (
      id INTEGER PRIMARY KEY,
      series_id INTEGER NOT NULL REFERENCES series(id),
      provider TEXT NOT NULL CHECK(provider='anilist'),
      provider_id INTEGER NOT NULL CHECK(provider_id > 0),
      state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
      evidence_ref TEXT NOT NULL CHECK(length(trim(evidence_ref)) > 0),
      actor TEXT NOT NULL CHECK(length(trim(actor)) > 0),
      created_at TEXT NOT NULL, revoked_at TEXT,
      CHECK ((state='ACTIVE' AND revoked_at IS NULL) OR
             (state='REVOKED' AND revoked_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX active_series_identity
      ON identity_bindings(series_id,provider) WHERE state='ACTIVE';
    CREATE UNIQUE INDEX active_provider_identity
      ON identity_bindings(provider,provider_id) WHERE state='ACTIVE';
    CREATE TABLE identity_audit (
      id INTEGER PRIMARY KEY, binding_id INTEGER NOT NULL REFERENCES identity_bindings(id),
      action TEXT NOT NULL CHECK(action IN ('BIND','REVOKE')),
      actor TEXT NOT NULL, evidence_ref TEXT NOT NULL,
      occurred_at TEXT NOT NULL
    );
    CREATE TRIGGER no_binding_delete BEFORE DELETE ON identity_bindings
      BEGIN SELECT RAISE(ABORT,'binding history cannot be deleted'); END;
    CREATE TRIGGER no_binding_rewrite BEFORE UPDATE ON identity_bindings
      WHEN OLD.series_id != NEW.series_id OR OLD.provider != NEW.provider
        OR OLD.provider_id != NEW.provider_id OR OLD.evidence_ref != NEW.evidence_ref
        OR OLD.actor != NEW.actor OR OLD.created_at != NEW.created_at
        OR OLD.state != 'ACTIVE' OR NEW.state != 'REVOKED'
        OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
      BEGIN SELECT RAISE(ABORT,'only ACTIVE to REVOKED permitted'); END;
    CREATE TRIGGER no_audit_update BEFORE UPDATE ON identity_audit
      BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
    CREATE TRIGGER no_audit_delete BEFORE DELETE ON identity_audit
      BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
    ''')


def _check_actor(actor, evidence_ref):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('privileged actor required')
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise ValueError('evidence reference required')


def bind(db, *, series_id, provider_id, actor, evidence_ref):
    """Privileged-only operation. Caller MUST authenticate actor independently."""
    _check_actor(actor, evidence_ref)
    if type(series_id) is not int or series_id <= 0:
        raise ValueError('invalid series ID')
    if type(provider_id) is not int or provider_id <= 0:
        raise ValueError('invalid AniList ID')
    timestamp = utcnow()
    with db:
        if not db.execute('SELECT 1 FROM series WHERE id=?', (series_id,)).fetchone():
            raise ValueError('unknown series')
        cursor = db.execute('''INSERT INTO identity_bindings
          (series_id,provider,provider_id,state,evidence_ref,actor,created_at)
          VALUES (?,'anilist',?,'ACTIVE',?,?,?)''',
          (series_id, provider_id, evidence_ref, actor, timestamp))
        db.execute('''INSERT INTO identity_audit
          (binding_id,action,actor,evidence_ref,occurred_at)
          VALUES (?,'BIND',?,?,?)''', (cursor.lastrowid, actor, evidence_ref, timestamp))
        return cursor.lastrowid


def revoke(db, *, binding_id, actor, evidence_ref):
    """Privileged-only operation. Revocation does not auto-rebind."""
    _check_actor(actor, evidence_ref)
    if type(binding_id) is not int or binding_id <= 0:
        raise ValueError('invalid binding ID')
    timestamp = utcnow()
    with db:
        cursor = db.execute('''UPDATE identity_bindings
          SET state='REVOKED', revoked_at=? WHERE id=? AND state='ACTIVE' ''',
          (timestamp, binding_id))
        if cursor.rowcount != 1:
            raise ValueError('active binding not found')
        db.execute('''INSERT INTO identity_audit
          (binding_id,action,actor,evidence_ref,occurred_at)
          VALUES (?,'REVOKE',?,?,?)''',
          (binding_id, actor, evidence_ref, timestamp))


def lookup(db, series_id):
    return db.execute('''SELECT provider,provider_id,id FROM identity_bindings
      WHERE series_id=? AND state='ACTIVE' ''', (series_id,)).fetchone()
