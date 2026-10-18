"""Offline schema rehearsal. Never opens the production controller database."""
import re
import sqlite3
from pathlib import Path

SCHEMA_SQL = r'''
CREATE TABLE identity_bindings (
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
 provider TEXT NOT NULL CHECK(provider IN ('anilist')),
 provider_id INTEGER NOT NULL CHECK(provider_id > 0),
 revision INTEGER NOT NULL CHECK(revision > 0),
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
 evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
 actor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 revoked_at TEXT, UNIQUE(series_id,provider,revision)
);
CREATE UNIQUE INDEX one_active_binding_per_series ON identity_bindings(series_id,provider) WHERE state='ACTIVE';
CREATE UNIQUE INDEX one_active_series_per_provider_id ON identity_bindings(provider,provider_id) WHERE state='ACTIVE';
CREATE TABLE mapping_approvals (
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
 binding_id INTEGER NOT NULL REFERENCES identity_bindings(id),
 revision INTEGER NOT NULL CHECK(revision>0),
 state TEXT NOT NULL CHECK(state IN ('APPROVED','REVOKED')),
 evidence_digest TEXT NOT NULL CHECK(length(evidence_digest)=64),
 actor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(series_id,revision)
);
CREATE UNIQUE INDEX one_active_mapping_per_series ON mapping_approvals(series_id) WHERE state='APPROVED';
CREATE TABLE mapping_entries (
 approval_id INTEGER NOT NULL REFERENCES mapping_approvals(id),
 release_episode INTEGER NOT NULL CHECK(release_episode>0),
 season INTEGER NOT NULL CHECK(season=1),
 episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 6),
 PRIMARY KEY(approval_id,release_episode), UNIQUE(approval_id,season,episode)
);
CREATE TRIGGER mapping_entries_no_update BEFORE UPDATE ON mapping_entries BEGIN SELECT RAISE(ABORT,'mapping entry immutable'); END;
CREATE TRIGGER mapping_entries_no_delete BEFORE DELETE ON mapping_entries BEGIN SELECT RAISE(ABORT,'mapping entry immutable'); END;
CREATE TRIGGER mapping_entries_no_insert_after_approval BEFORE INSERT ON mapping_entries
 WHEN (SELECT state FROM mapping_approvals WHERE id=NEW.approval_id)='APPROVED'
 BEGIN SELECT RAISE(ABORT,'approved mapping immutable'); END;
CREATE TABLE trial_decisions (
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL UNIQUE REFERENCES series(id),
 approval_id INTEGER NOT NULL REFERENCES mapping_approvals(id),
 action TEXT NOT NULL CHECK(action IN ('KEEP','REJECT')),
 actor TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE cancellation_jobs (
 id INTEGER PRIMARY KEY, decision_id INTEGER NOT NULL REFERENCES trial_decisions(id),
 attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
 torrent_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING'
 CHECK(state IN ('PENDING','CLAIMED','RETRY','DONE','BLOCKED')),
 generation INTEGER NOT NULL DEFAULT 0 CHECK(generation>=0),
 lease_token TEXT, lease_until INTEGER,
 UNIQUE(decision_id,attempt_id)
);
CREATE TABLE integration_audit (
 id INTEGER PRIMARY KEY, event_type TEXT NOT NULL,
 series_id INTEGER NOT NULL REFERENCES series(id), detail TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER integration_audit_no_update BEFORE UPDATE ON integration_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER integration_audit_no_delete BEFORE DELETE ON integration_audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
'''


def extract_existing_schema(inspection_text):
    # Extract the exact CREATE TABLE statements printed by the read-only inspection.
    chunks = re.findall(r'(?ms)^TABLE: ([a-z_]+)\n(CREATE TABLE .*?)(?=\n\n(?:TABLE:|=== FOREIGN KEYS ===))', inspection_text)
    expected = {'series','episodes','download_attempts','staged_episodes','file_observations'}
    found = {name for name, _ in chunks}
    if found != expected or len(chunks) != 5:
        raise ValueError(f'Unexpected inspection tables: {found}')
    return [sql.strip() for _, sql in chunks]


def make_rehearsal_database(inspection_text):
    conn = sqlite3.connect(':memory:')
    conn.execute('PRAGMA foreign_keys=ON')
    for statement in extract_existing_schema(inspection_text):
        conn.execute(statement)
    before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.executescript(SCHEMA_SQL)
    after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not before.issubset(after):
        raise AssertionError('Existing table removed')
    return conn


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('inspection', type=Path)
    args = parser.parse_args()
    conn = make_rehearsal_database(args.inspection.read_text())
    print('Original tables preserved; new tables installed in memory only.')
    print('quick_check:', conn.execute('PRAGMA quick_check').fetchone()[0])
    print('foreign_key_check:', conn.execute('PRAGMA foreign_key_check').fetchall())
    print('new tables:', ', '.join(sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('identity_bindings','mapping_approvals','mapping_entries','trial_decisions','cancellation_jobs','integration_audit')"))))
    conn.close()

if __name__ == '__main__':
    main()
