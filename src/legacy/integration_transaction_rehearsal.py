"""Phase 2X-AB: offline-only transactional integration rehearsal.

Only accepts an in-memory SQLite connection created from the inspected schema.
Never opens a production database, performs network requests, or executes jobs.
"""
import sqlite3
from integration_schema_rehearsal import make_rehearsal_database


class ContractError(ValueError):
    pass


def require_memory(conn):
    databases = conn.execute('PRAGMA database_list').fetchall()
    if len(databases) != 1 or databases[0][2] != '':
        raise ContractError('Only a single in-memory SQLite database is permitted')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise ContractError('Foreign keys must be enabled')


def seed_fixture(conn):
    require_memory(conn)
    with conn:
        conn.execute("INSERT INTO series(id,source,external_id,title,status) VALUES(9001,'test','AB-9001','Offline Fixture','PENDING_REVIEW')")
        for episode in range(1, 4):
            conn.execute("INSERT INTO episodes(series_id,season,episode) VALUES(9001,1,?)", (episode,))
        conn.execute("INSERT INTO download_attempts(id,series_id,season,episode,torrent_hash,release_title,status) VALUES(9101,9001,1,2,?,?,'DOWNLOADING')", ('a'*40, 'Fixture - 02'))
        conn.execute("INSERT INTO download_attempts(id,series_id,season,episode,torrent_hash,release_title,status) VALUES(9102,9001,1,3,?,?,'DOWNLOADING')", ('b'*40, 'Fixture - 03'))
        conn.execute("INSERT INTO identity_bindings(id,series_id,provider,provider_id,revision,state,evidence_digest,actor) VALUES(9201,9001,'anilist',11061,1,'ACTIVE',?,'fixture-admin')", ('c'*64,))
        conn.execute("INSERT INTO mapping_approvals(id,series_id,binding_id,revision,state,evidence_digest,actor) VALUES(9301,9001,9201,1,'APPROVED',?,'fixture-admin')", ('d'*64,))
    return conn


def rehearse_decision(conn, *, action='KEEP', fail_at=None):
    """Demonstrate atomic decision/outbox/audit writes on the *existing* rehearsal schema.

    Does NOT authorize the decision, validate Episode 1 watchability, or cancel torrents.
    """
    require_memory(conn)
    if action not in ('KEEP', 'REJECT'):
        raise ContractError('Unsupported decision')
    if conn.in_transaction:
        raise ContractError('Connection must have no open transaction')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT s.status, a.id, a.state, b.state FROM series s JOIN mapping_approvals a ON a.series_id=s.id JOIN identity_bindings b ON b.id=a.binding_id WHERE s.id=9001 AND a.id=9301").fetchone()
        if row != ('PENDING_REVIEW', 9301, 'APPROVED', 'ACTIVE'):
            raise ContractError('Fixture state or approval changed')
        prior = conn.execute('SELECT id,action FROM trial_decisions WHERE series_id=9001').fetchone()
        if prior:
            if prior[1] != action:
                raise ContractError('Conflicting decision')
            conn.execute('COMMIT')
            return prior[0]
        cursor = conn.execute("INSERT INTO trial_decisions(series_id,approval_id,action,actor) VALUES(9001,9301,?,'fixture-user')", (action,))
        decision_id = cursor.lastrowid
        if fail_at == 'decision':
            raise RuntimeError('Injected failure after decision')
        attempts = conn.execute("SELECT id,torrent_hash FROM download_attempts WHERE series_id=9001 AND status IN ('QUEUED','DOWNLOADING','STALLED') ORDER BY id").fetchall()
        for attempt_id, torrent_hash in attempts:
            conn.execute("INSERT INTO cancellation_jobs(decision_id,attempt_id,torrent_hash) VALUES(?,?,?)", (decision_id, attempt_id, torrent_hash))
        if fail_at == 'outbox':
            raise RuntimeError('Injected failure after outbox')
        conn.execute("INSERT INTO integration_audit(event_type,series_id,detail) VALUES('TRIAL_DECISION',9001,?)", (action,))
        if fail_at == 'audit':
            raise RuntimeError('Injected failure after audit')
        conn.execute('COMMIT')
        return decision_id
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise


def inventory(conn):
    require_memory(conn)
    return {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('trial_decisions','cancellation_jobs','integration_audit')}


def build_fixture(inspection_text):
    return seed_fixture(make_rehearsal_database(inspection_text))
