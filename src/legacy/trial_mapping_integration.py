"""2X-AD: in-memory-only mapping/decision integration rehearsal.

No auth, real media verification, external cancellation, or production API wiring.
"""
from integration_transaction_rehearsal import require_memory, ContractError


def install(conn):
    require_memory(conn)
    conn.executescript("""
    CREATE TABLE trial_decisions_v2 (
      id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL UNIQUE REFERENCES series(id),
      mapping_id INTEGER NOT NULL REFERENCES mapping_drafts_v2(id),
      action TEXT NOT NULL CHECK(action IN ('KEEP','REJECT')), actor TEXT NOT NULL
    );
    CREATE TABLE cancellation_jobs_v2 (
      id INTEGER PRIMARY KEY, decision_id INTEGER NOT NULL REFERENCES trial_decisions_v2(id),
      attempt_id INTEGER NOT NULL REFERENCES download_attempts(id), torrent_hash TEXT NOT NULL,
      UNIQUE(decision_id,attempt_id)
    );
    CREATE TABLE integration_audit_v2 (
      id INTEGER PRIMARY KEY, decision_id INTEGER NOT NULL REFERENCES trial_decisions_v2(id),
      detail TEXT NOT NULL
    );
    """)


def decide(conn, *, series_id, draft_id, action, actor, episode_one_verified=False, fail_at=None):
    require_memory(conn)
    if action not in ('KEEP', 'REJECT') or not actor or not actor.strip():
        raise ContractError('invalid decision')
    # Caller assertion is TEST-ONLY; never use as a production watchability proof.
    if episode_one_verified is not True:
        raise ContractError('episode one verification required')
    if conn.in_transaction:
        raise ContractError('active transaction')
    try:
        conn.execute('BEGIN IMMEDIATE')
        mapping = conn.execute('''SELECT d.series_id,d.state,b.state,s.status
            FROM mapping_drafts_v2 d JOIN identity_bindings b ON b.id=d.binding_id
            JOIN series s ON s.id=d.series_id WHERE d.id=?''',(draft_id,)).fetchone()
        if mapping != (series_id,'APPROVED','ACTIVE','PENDING_REVIEW'):
            raise ContractError('mapping, identity or trial state invalid')
        entries = conn.execute('SELECT episode FROM mapping_draft_entries_v2 WHERE draft_id=? ORDER BY episode',(draft_id,)).fetchall()
        if not entries or [e[0] for e in entries] != list(range(1,len(entries)+1)):
            raise ContractError('mapping no longer contiguous')
        previous = conn.execute('SELECT id,action,mapping_id FROM trial_decisions_v2 WHERE series_id=?',(series_id,)).fetchone()
        if previous:
            if previous[1:] != (action,draft_id):
                raise ContractError('conflicting decision')
            conn.execute('COMMIT')
            return previous[0]
        cur=conn.execute('INSERT INTO trial_decisions_v2(series_id,mapping_id,action,actor) VALUES(?,?,?,?)',
                         (series_id,draft_id,action,actor))
        decision_id=cur.lastrowid
        if fail_at=='decision': raise RuntimeError('injected failure')
        attempts=conn.execute('''SELECT id,torrent_hash FROM download_attempts
            WHERE series_id=? AND status IN ('QUEUED','DOWNLOADING','STALLED') ORDER BY id''',(series_id,)).fetchall()
        for attempt_id,torrent_hash in attempts:
            conn.execute('INSERT INTO cancellation_jobs_v2(decision_id,attempt_id,torrent_hash) VALUES(?,?,?)',
                         (decision_id,attempt_id,torrent_hash))
        if fail_at=='outbox': raise RuntimeError('injected failure')
        conn.execute("INSERT INTO integration_audit_v2(decision_id,detail) VALUES(?,?)",
                     (decision_id, f'{action}:mapping_v2:{draft_id}'))
        if fail_at=='audit': raise RuntimeError('injected failure')
        conn.execute('COMMIT')
        return decision_id
    except BaseException:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
