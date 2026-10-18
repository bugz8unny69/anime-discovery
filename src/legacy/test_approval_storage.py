import sqlite3

SCHEMA = '''
PRAGMA foreign_keys = ON;
CREATE TABLE series (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
 title TEXT NOT NULL, UNIQUE(source,external_id)
);
CREATE TABLE mapping_revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE RESTRICT,
 revision INTEGER NOT NULL CHECK(revision >= 1),
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REVOKED')),
 approval_method TEXT CHECK(approval_method IN ('manual','verified_metadata')),
 approved_by TEXT, approved_at TEXT, revoked_at TEXT,
 UNIQUE(series_id,revision),
 CHECK (
  (status='PENDING' AND approval_method IS NULL AND approved_by IS NULL AND approved_at IS NULL AND revoked_at IS NULL)
  OR (status='APPROVED' AND approval_method IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND revoked_at IS NULL)
  OR (status='REVOKED' AND approval_method IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL AND revoked_at IS NOT NULL)
 )
);
CREATE UNIQUE INDEX one_approved_mapping_per_series
 ON mapping_revisions(series_id) WHERE status='APPROVED';
CREATE TABLE mapping_entries (
 revision_id INTEGER NOT NULL REFERENCES mapping_revisions(id) ON DELETE RESTRICT,
 release_episode INTEGER NOT NULL CHECK(release_episode >= 1),
 canonical_season INTEGER NOT NULL CHECK(canonical_season = 1),
 canonical_episode INTEGER NOT NULL CHECK(canonical_episode BETWEEN 1 AND 6),
 PRIMARY KEY(revision_id,release_episode),
 UNIQUE(revision_id,canonical_season,canonical_episode)
);
CREATE TABLE mapping_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 revision_id INTEGER NOT NULL REFERENCES mapping_revisions(id) ON DELETE RESTRICT,
 action TEXT NOT NULL CHECK(action IN ('CREATE','APPROVE','REVOKE')),
 actor TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER entries_insert_guard BEFORE INSERT ON mapping_entries
WHEN (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id) != 'PENDING'
BEGIN SELECT RAISE(ABORT,'mapping is immutable'); END;
CREATE TRIGGER entries_update_guard BEFORE UPDATE ON mapping_entries
WHEN (SELECT status FROM mapping_revisions WHERE id=OLD.revision_id) != 'PENDING'
  OR (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id) != 'PENDING'
BEGIN SELECT RAISE(ABORT,'mapping is immutable'); END;
CREATE TRIGGER entries_delete_guard BEFORE DELETE ON mapping_entries
WHEN (SELECT status FROM mapping_revisions WHERE id=OLD.revision_id) != 'PENDING'
BEGIN SELECT RAISE(ABORT,'mapping is immutable'); END;
CREATE TRIGGER revision_update_guard BEFORE UPDATE ON mapping_revisions
BEGIN
 SELECT CASE WHEN NEW.id != OLD.id OR NEW.series_id != OLD.series_id OR NEW.revision != OLD.revision
  THEN RAISE(ABORT,'revision identity immutable') END;
 SELECT CASE WHEN NOT (
   (OLD.status='PENDING' AND NEW.status='APPROVED' AND NEW.approval_method IS NOT NULL
    AND NEW.approved_by IS NOT NULL AND NEW.approved_at IS NOT NULL AND NEW.revoked_at IS NULL)
   OR (OLD.status='APPROVED' AND NEW.status='REVOKED' AND NEW.approval_method=OLD.approval_method
    AND NEW.approved_by=OLD.approved_by AND NEW.approved_at=OLD.approved_at AND NEW.revoked_at IS NOT NULL)
  ) THEN RAISE(ABORT,'invalid mapping lifecycle transition') END;
 SELECT CASE WHEN OLD.status='PENDING' AND NOT EXISTS(
  SELECT 1 FROM mapping_entries WHERE revision_id=OLD.id
 ) THEN RAISE(ABORT,'empty mapping cannot be approved') END;
END;
CREATE TRIGGER revision_delete_guard BEFORE DELETE ON mapping_revisions
BEGIN SELECT RAISE(ABORT,'mapping revisions cannot be deleted'); END;
CREATE TRIGGER audit_update_guard BEFORE UPDATE ON mapping_audit
BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER audit_delete_guard BEFORE DELETE ON mapping_audit
BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER audit_insert_guard BEFORE INSERT ON mapping_audit
WHEN NOT (
 (NEW.action='CREATE' AND (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id)='PENDING')
 OR (NEW.action='APPROVE' AND (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id)='APPROVED')
 OR (NEW.action='REVOKE' AND (SELECT status FROM mapping_revisions WHERE id=NEW.revision_id)='REVOKED')
)
BEGIN SELECT RAISE(ABORT,'audit action inconsistent with status'); END;
'''


def new_db():
    db = sqlite3.connect(':memory:')
    db.executescript(SCHEMA)
    db.execute("INSERT INTO series VALUES (7,'test','TEST-007','Example Anime')")
    db.execute("INSERT INTO series VALUES (8,'test','TEST-008','Other Anime')")
    return db


def create_revision(db, series_id, revision, entries, actor='admin'):
    with db:
        cur = db.execute('INSERT INTO mapping_revisions(series_id,revision) VALUES (?,?)', (series_id,revision))
        rid = cur.lastrowid
        for source, episode in entries.items():
            db.execute('INSERT INTO mapping_entries VALUES (?,?,?,?)', (rid,source,1,episode))
        db.execute("INSERT INTO mapping_audit(revision_id,action,actor) VALUES (?,'CREATE',?)", (rid,actor))
    return rid


def approve(db, rid, method='manual', actor='admin'):
    with db:
        db.execute("UPDATE mapping_revisions SET status='APPROVED',approval_method=?,approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=? AND status='PENDING'", (method,actor,rid))
        if db.execute('SELECT changes()').fetchone()[0] != 1:
            raise ValueError('revision is not pending')
        db.execute("INSERT INTO mapping_audit(revision_id,action,actor) VALUES (?,'APPROVE',?)",(rid,actor))


def revoke(db, rid, actor='admin'):
    with db:
        db.execute("UPDATE mapping_revisions SET status='REVOKED',revoked_at=CURRENT_TIMESTAMP WHERE id=? AND status='APPROVED'", (rid,))
        if db.execute('SELECT changes()').fetchone()[0] != 1:
            raise ValueError('revision is not approved')
        db.execute("INSERT INTO mapping_audit(revision_id,action,actor) VALUES (?,'REVOKE',?)",(rid,actor))


def trusted_lookup(db, series_id, release_episode):
    rows = db.execute('''SELECT r.revision,e.canonical_season,e.canonical_episode
      FROM mapping_revisions r JOIN mapping_entries e ON e.revision_id=r.id
      WHERE r.series_id=? AND r.status='APPROVED' AND e.release_episode=?''',
      (series_id,release_episode)).fetchall()
    return rows[0] if len(rows)==1 else None


def blocked(name, action):
    try:
        action()
    except (sqlite3.IntegrityError, ValueError):
        print('PASS',name)
    else:
        raise AssertionError('Unexpectedly allowed: '+name)


def run():
    db=new_db()
    rid=create_revision(db,7,1,{1:1,2:2})
    assert trusted_lookup(db,7,1) is None
    print('PASS pending mapping cannot authorize')
    approve(db,rid)
    assert trusted_lookup(db,7,2)==(1,1,2)
    assert trusted_lookup(db,8,2) is None
    assert trusted_lookup(db,7,3) is None
    print('PASS trusted lookup scoped to approved series and mapped episode')
    blocked('approved insert blocked',lambda: db.execute('INSERT INTO mapping_entries VALUES (?,3,1,3)',(rid,)))
    blocked('approved update blocked',lambda: db.execute('UPDATE mapping_entries SET canonical_episode=3 WHERE revision_id=? AND release_episode=2',(rid,)))
    blocked('approved delete blocked',lambda: db.execute('DELETE FROM mapping_entries WHERE revision_id=?',(rid,)))
    blocked('approved-to-pending blocked',lambda: db.execute("UPDATE mapping_revisions SET status='PENDING',approval_method=NULL,approved_by=NULL,approved_at=NULL WHERE id=?",(rid,)))
    blocked('approval actor tampering blocked',lambda: db.execute("UPDATE mapping_revisions SET approved_by='intruder' WHERE id=?",(rid,)))
    blocked('revision identity tampering blocked',lambda: db.execute('UPDATE mapping_revisions SET series_id=8 WHERE id=?',(rid,)))
    blocked('revision deletion blocked',lambda: db.execute('DELETE FROM mapping_revisions WHERE id=?',(rid,)))
    blocked('audit update blocked',lambda: db.execute("UPDATE mapping_audit SET actor='intruder' WHERE revision_id=?",(rid,)))
    blocked('audit deletion blocked',lambda: db.execute('DELETE FROM mapping_audit WHERE revision_id=?',(rid,)))
    blocked('second approved revision blocked',lambda: approve(db,create_revision(db,7,2,{1:1})))
    assert db.execute("SELECT status FROM mapping_revisions WHERE series_id=7 AND revision=2").fetchone()[0]=='PENDING'
    print('PASS failed approval transaction leaves revision pending')
    assert db.execute("SELECT count(*) FROM mapping_audit WHERE action='APPROVE'").fetchone()[0]==1
    print('PASS failed approval does not append audit event')
    revoke(db,rid)
    assert trusted_lookup(db,7,1) is None
    print('PASS revoked mapping fails closed')
    blocked('revoked-to-approved blocked',lambda: db.execute("UPDATE mapping_revisions SET status='APPROVED',revoked_at=NULL WHERE id=?",(rid,)))
    blocked('revoked entry update blocked',lambda: db.execute('UPDATE mapping_entries SET canonical_episode=3 WHERE revision_id=? AND release_episode=2',(rid,)))
    rid2=db.execute('SELECT id FROM mapping_revisions WHERE series_id=7 AND revision=2').fetchone()[0]
    approve(db,rid2)
    assert trusted_lookup(db,7,1)==(2,1,1)
    print('PASS new approved revision replaces revoked revision without deleting history')
    blocked('duplicate revision blocked',lambda: create_revision(db,7,2,{1:1}))
    blocked('foreign key enforced',lambda: create_revision(db,999,1,{1:1}))
    blocked('duplicate canonical target blocked',lambda: create_revision(db,8,1,{1:1,2:1}))
    blocked('out-of-trial episode blocked',lambda: create_revision(db,8,1,{1:7}))
    blocked('empty mapping cannot be approved',lambda: approve(db,create_revision(db,8,1,{})))
    assert db.execute("SELECT count(*) FROM mapping_audit WHERE revision_id=? AND action='REVOKE'",(rid,)).fetchone()[0]==1
    print('PASS revocation audit recorded')
    db.close()
    print('\nAll consolidated approval-storage tests passed.')

if __name__=='__main__':
    run()
