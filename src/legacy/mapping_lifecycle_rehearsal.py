"""Phase 2X-AC: isolated mapping lifecycle, never touches a file-backed DB.

This is a proposed V2 contract, NOT a production migration or trust verifier.
"""
import re
import sqlite3
from integration_transaction_rehearsal import require_memory, ContractError

V2_SQL = '''
CREATE TABLE mapping_drafts_v2 (
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
 binding_id INTEGER NOT NULL REFERENCES identity_bindings(id),
 revision INTEGER NOT NULL CHECK(revision>0),
 evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
 actor TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'DRAFT'
 CHECK(state IN ('DRAFT','APPROVED','REVOKED')),
 UNIQUE(series_id,revision)
);
CREATE UNIQUE INDEX mapping_v2_one_active ON mapping_drafts_v2(series_id) WHERE state='APPROVED';
CREATE TABLE mapping_draft_entries_v2 (
 draft_id INTEGER NOT NULL REFERENCES mapping_drafts_v2(id),
 release_episode INTEGER NOT NULL CHECK(release_episode>0),
 season INTEGER NOT NULL CHECK(season=1),
 episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 6),
 PRIMARY KEY(draft_id,release_episode), UNIQUE(draft_id,season,episode)
);
CREATE TABLE mapping_lifecycle_events_v2 (
 id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES mapping_drafts_v2(id),
 event TEXT NOT NULL CHECK(event IN ('APPROVED','REVOKED')),
 actor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER v2_entry_insert_guard BEFORE INSERT ON mapping_draft_entries_v2
 WHEN (SELECT state FROM mapping_drafts_v2 WHERE id=NEW.draft_id)!='DRAFT'
 BEGIN SELECT RAISE(ABORT,'sealed mapping'); END;
CREATE TRIGGER v2_entry_update_guard BEFORE UPDATE ON mapping_draft_entries_v2
 BEGIN SELECT RAISE(ABORT,'mapping entries immutable'); END;
CREATE TRIGGER v2_entry_delete_guard BEFORE DELETE ON mapping_draft_entries_v2
 BEGIN SELECT RAISE(ABORT,'mapping entries immutable'); END;
CREATE TRIGGER v2_event_update_guard BEFORE UPDATE ON mapping_lifecycle_events_v2
 BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER v2_event_delete_guard BEFORE DELETE ON mapping_lifecycle_events_v2
 BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER v2_draft_delete_guard BEFORE DELETE ON mapping_drafts_v2
 BEGIN SELECT RAISE(ABORT,'draft immutable'); END;
CREATE TRIGGER v2_draft_update_guard BEFORE UPDATE ON mapping_drafts_v2
 WHEN NOT (OLD.state='DRAFT' AND NEW.state='APPROVED' OR OLD.state='APPROVED' AND NEW.state='REVOKED')
 OR OLD.id!=NEW.id OR OLD.series_id!=NEW.series_id OR OLD.binding_id!=NEW.binding_id
 OR OLD.revision!=NEW.revision OR OLD.evidence_digest!=NEW.evidence_digest OR OLD.actor!=NEW.actor
 BEGIN SELECT RAISE(ABORT,'invalid lifecycle transition'); END;
'''

def install(conn):
    require_memory(conn)
    conn.executescript(V2_SQL)

def _tx(conn, fn):
    require_memory(conn)
    if conn.in_transaction:
        raise ContractError('transaction already active')
    try:
        conn.execute('BEGIN IMMEDIATE')
        result = fn()
        conn.execute('COMMIT')
        return result
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise

def create_draft(conn, *, series_id, binding_id, revision, evidence_digest, actor):
    if not re.fullmatch('[0-9a-f]{64}', evidence_digest):
        raise ContractError('invalid digest')
    if not actor or not actor.strip():
        raise ContractError('actor required')
    def operation():
        row = conn.execute('SELECT series_id,state FROM identity_bindings WHERE id=?', (binding_id,)).fetchone()
        if row != (series_id,'ACTIVE'):
            raise ContractError('binding not active for series')
        return conn.execute('INSERT INTO mapping_drafts_v2(series_id,binding_id,revision,evidence_digest,actor) VALUES(?,?,?,?,?)',
                            (series_id,binding_id,revision,evidence_digest,actor)).lastrowid
    return _tx(conn, operation)

def add_entry(conn, draft_id, release_episode, canonical_episode):
    def operation():
        row = conn.execute('SELECT state FROM mapping_drafts_v2 WHERE id=?',(draft_id,)).fetchone()
        if row != ('DRAFT',):
            raise ContractError('draft not editable')
        conn.execute('INSERT INTO mapping_draft_entries_v2 VALUES(?,?,1,?)',(draft_id,release_episode,canonical_episode))
    return _tx(conn,operation)

def approve(conn, draft_id, *, actor, trusted_evidence_verified=False, fail_at=None):
    """trusted_evidence_verified is a test-only assertion; never expose as authorization."""
    if not trusted_evidence_verified:
        raise ContractError('trusted evidence not verified by external gateway')
    if not actor or not actor.strip():
        raise ContractError('actor required')
    def operation():
        row = conn.execute('SELECT series_id,binding_id,state FROM mapping_drafts_v2 WHERE id=?',(draft_id,)).fetchone()
        if not row or row[2]!='DRAFT':
            raise ContractError('not an approvable draft')
        series_id,binding_id,_ = row
        if conn.execute('SELECT series_id,state FROM identity_bindings WHERE id=?',(binding_id,)).fetchone() != (series_id,'ACTIVE'):
            raise ContractError('identity revoked or mismatched')
        entries = conn.execute('SELECT release_episode,episode FROM mapping_draft_entries_v2 WHERE draft_id=? ORDER BY episode',(draft_id,)).fetchall()
        if not entries or [e for _,e in entries] != list(range(1,len(entries)+1)):
            raise ContractError('mapping must contain contiguous canonical prefix from 1')
        if len({r for r,_ in entries})!=len(entries):
            raise ContractError('duplicate release episode')
        conn.execute("UPDATE mapping_drafts_v2 SET state='APPROVED' WHERE id=?",(draft_id,))
        if fail_at=='seal':
            raise RuntimeError('injected seal failure')
        conn.execute("INSERT INTO mapping_lifecycle_events_v2(draft_id,event,actor) VALUES(?,'APPROVED',?)",(draft_id,actor))
        if fail_at=='audit':
            raise RuntimeError('injected audit failure')
        return draft_id
    return _tx(conn,operation)

def revoke(conn,draft_id,*,actor):
    if not actor or not actor.strip():
        raise ContractError('actor required')
    def operation():
        if conn.execute('SELECT state FROM mapping_drafts_v2 WHERE id=?',(draft_id,)).fetchone()!=('APPROVED',):
            raise ContractError('only approved mapping can be revoked')
        conn.execute("UPDATE mapping_drafts_v2 SET state='REVOKED' WHERE id=?",(draft_id,))
        conn.execute("INSERT INTO mapping_lifecycle_events_v2(draft_id,event,actor) VALUES(?,'REVOKED',?)",(draft_id,actor))
    return _tx(conn,operation)
