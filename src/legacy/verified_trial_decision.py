"""Phase 2X-AF. In-memory-only authenticated decision rehearsal.

A DB-backed media observation is *necessary*, not sufficient, evidence of playback.
No real ffprobe, filesystem, HTTP auth, or torrent operations are performed.
"""
import hashlib
import hmac
import json
from integration_transaction_rehearsal import require_memory, ContractError

DOMAIN = b'anime-discovery/trial-decision/v1\0'


def _payload_bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def sign_test_decision(key, *, series_id, mapping_id, action, nonce, issued_at, expires_at):
    """Test fixture signing only. Never expose this signer on an API."""
    payload = dict(series_id=series_id, mapping_id=mapping_id, action=action,
                   nonce=nonce, issued_at=issued_at, expires_at=expires_at)
    return dict(payload=payload, signature=hmac.new(key, DOMAIN + _payload_bytes(payload), hashlib.sha256).hexdigest())


def install(db):
    require_memory(db)
    db.executescript('''
    CREATE TABLE verified_media_v4 (
      id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
      mapping_id INTEGER NOT NULL REFERENCES mapping_drafts_v2(id),
      attempt_id INTEGER NOT NULL REFERENCES download_attempts(id),
      season INTEGER NOT NULL CHECK(season=1), episode INTEGER NOT NULL CHECK(episode=1),
      staged_path TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
      mtime_ns INTEGER NOT NULL, observed_at INTEGER NOT NULL,
      verifier TEXT NOT NULL CHECK(verifier='SYNTHETIC_TEST_ONLY'),
      UNIQUE(series_id,mapping_id,attempt_id)
    );
    CREATE TABLE trial_nonces_v4 (
      nonce TEXT PRIMARY KEY, decision_id INTEGER NOT NULL REFERENCES trial_decisions_v2(id)
    );
    CREATE TRIGGER media_v4_no_update BEFORE UPDATE ON verified_media_v4
    BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
    CREATE TRIGGER media_v4_no_delete BEFORE DELETE ON verified_media_v4
    BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
    CREATE TRIGGER nonce_v4_no_update BEFORE UPDATE ON trial_nonces_v4
    BEGIN SELECT RAISE(ABORT,'immutable nonce'); END;
    CREATE TRIGGER nonce_v4_no_delete BEFORE DELETE ON trial_nonces_v4
    BEGIN SELECT RAISE(ABORT,'immutable nonce'); END;
    ''')


def verify_request(envelope, key, now, series_id, mapping_id):
    if type(key) is not bytes or len(key) < 32 or type(now) is not int:
        raise ContractError('invalid verification configuration')
    if type(envelope) is not dict or set(envelope) != {'payload','signature'}:
        raise ContractError('invalid envelope')
    p = envelope['payload']
    if type(p) is not dict or set(p) != {'series_id','mapping_id','action','nonce','issued_at','expires_at'}:
        raise ContractError('invalid payload')
    if type(p['series_id']) is not int or p['series_id'] != series_id or type(p['mapping_id']) is not int or p['mapping_id'] != mapping_id:
        raise ContractError('target mismatch')
    if p['action'] not in ('KEEP','REJECT') or type(p['nonce']) is not str or len(p['nonce']) < 16 or len(p['nonce']) > 128 or not p['nonce'].isascii() or not p['nonce'].isalnum():
        raise ContractError('invalid action or nonce')
    if type(p['issued_at']) is not int or type(p['expires_at']) is not int or not (p['issued_at'] - 30 <= now < p['expires_at'] <= p['issued_at'] + 300):
        raise ContractError('expired request')
    sig = envelope['signature']
    expected = hmac.new(key, DOMAIN + _payload_bytes(p), hashlib.sha256).hexdigest()
    if type(sig) is not str or not hmac.compare_digest(sig, expected):
        raise ContractError('invalid signature')
    return p


def record_synthetic_observation(db, *, series_id, mapping_id, attempt_id, observed_at):
    """Copy existing DB facts into a synthetic proof; never claims real ffprobe success."""
    require_memory(db)
    row = db.execute('''SELECT st.staged_path, fo.size_bytes, fo.mtime_ns
       FROM staged_episodes st JOIN file_observations fo
       ON (st.series_id,st.season,st.episode)=(fo.series_id,fo.season,fo.episode)
       WHERE st.series_id=? AND st.season=1 AND st.episode=1
         AND st.attempt_id=? AND st.status='STAGED' AND fo.staged_path=st.staged_path
         AND fo.size_bytes>0''', (series_id, attempt_id)).fetchone()
    if row is None or type(observed_at) is not int:
        raise ContractError('no matching staged episode one observation')
    return db.execute('''INSERT INTO verified_media_v4
       (series_id,mapping_id,attempt_id,season,episode,staged_path,size_bytes,mtime_ns,observed_at,verifier)
       VALUES (?,?,?,1,1,?,?,?,?,'SYNTHETIC_TEST_ONLY')''',
       (series_id,mapping_id,attempt_id,*row,observed_at)).lastrowid


def decide_authenticated(db, *, series_id, mapping_id, envelope, key, now,
                         max_age=300, fail_at=None):
    require_memory(db)
    p = verify_request(envelope, key, now, series_id, mapping_id)
    if type(max_age) is not int or max_age < 0 or db.in_transaction:
        raise ContractError('invalid transaction state')
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM trial_nonces_v4 WHERE nonce=?', (p['nonce'],)).fetchone():
            raise ContractError('replayed nonce')
        state = db.execute('''SELECT d.series_id,d.state,b.state,s.status
           FROM mapping_drafts_v2 d JOIN identity_bindings b ON b.id=d.binding_id
           JOIN series s ON s.id=d.series_id WHERE d.id=?''',(mapping_id,)).fetchone()
        if state != (series_id,'APPROVED','ACTIVE','PENDING_REVIEW'):
            raise ContractError('mapping or trial no longer valid')
        entries = db.execute('SELECT episode FROM mapping_draft_entries_v2 WHERE draft_id=? ORDER BY episode',(mapping_id,)).fetchall()
        if not entries or [x[0] for x in entries] != list(range(1,len(entries)+1)):
            raise ContractError('invalid canonical mapping')
        proof = db.execute('''SELECT attempt_id,staged_path,size_bytes,mtime_ns,observed_at
           FROM verified_media_v4 WHERE series_id=? AND mapping_id=?
           ORDER BY observed_at DESC LIMIT 1''',(series_id,mapping_id)).fetchone()
        if not proof or proof[4] > now or now - proof[4] > max_age:
            raise ContractError('missing or stale media observation')
        attempt_id,path,size,mtime,_ = proof
        live = db.execute('''SELECT a.series_id,a.season,a.episode,a.status,st.staged_path,
             st.status,fo.staged_path,fo.size_bytes,fo.mtime_ns
             FROM download_attempts a JOIN staged_episodes st ON st.attempt_id=a.id
             JOIN file_observations fo ON (fo.series_id,fo.season,fo.episode)=(st.series_id,st.season,st.episode)
             WHERE a.id=? AND st.series_id=? AND st.season=1 AND st.episode=1''', (attempt_id,series_id)).fetchone()
        if live != (series_id,1,1,'COMPLETED',path,'STAGED',path,size,mtime):
            raise ContractError('stale attempt or changed file observation')
        prior = db.execute('SELECT id FROM trial_decisions_v2 WHERE series_id=?',(series_id,)).fetchone()
        if prior:
            raise ContractError('trial already decided')
        cursor = db.execute('INSERT INTO trial_decisions_v2(series_id,mapping_id,action,actor) VALUES(?,?,?,?)',
                            (series_id,mapping_id,p['action'],'signed-trial-user'))
        decision_id = cursor.lastrowid
        if fail_at == 'decision': raise RuntimeError('injected failure')
        for aid, thash in db.execute('''SELECT id,torrent_hash FROM download_attempts
              WHERE series_id=? AND status IN ('QUEUED','DOWNLOADING','STALLED') ORDER BY id''',(series_id,)):
            db.execute('INSERT INTO cancellation_jobs_v2(decision_id,attempt_id,torrent_hash) VALUES(?,?,?)',
                       (decision_id,aid,thash))
        if fail_at == 'outbox': raise RuntimeError('injected failure')
        db.execute('INSERT INTO trial_nonces_v4(nonce,decision_id) VALUES(?,?)',(p['nonce'],decision_id))
        db.execute('INSERT INTO integration_audit_v2(decision_id,detail) VALUES(?,?)',
                   (decision_id, f"{p['action']}:authenticated-synthetic-proof"))
        if fail_at == 'audit': raise RuntimeError('injected failure')
        db.execute('COMMIT')
        return decision_id
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise
