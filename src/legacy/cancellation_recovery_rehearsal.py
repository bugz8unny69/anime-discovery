"""2X-AG: offline cancellation recovery contract. NEVER sends qBittorrent requests.

A successful preflight is not permission to delete: an external actor can change
qBittorrent state immediately afterwards. Only verified absence can complete a job.
"""
import secrets
from dataclasses import dataclass
from integration_transaction_rehearsal import require_memory, ContractError

ACTIVE = ('QUEUED', 'DOWNLOADING', 'STALLED')

@dataclass(frozen=True)
class Inventory:
    torrent_hash: str
    present: bool
    attempt_id: int
    generation: int
    observed_at: int


def install(db):
    require_memory(db)
    db.executescript('''
    CREATE TABLE cancellation_recovery_v5 (
      job_id INTEGER PRIMARY KEY REFERENCES cancellation_jobs_v2(id),
      state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','LEASED','DONE','BLOCKED')),
      generation INTEGER NOT NULL DEFAULT 0 CHECK(generation>=0),
      token TEXT, lease_until INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
      next_at INTEGER NOT NULL DEFAULT 0, last_reason TEXT,
      CHECK((state='LEASED' AND token IS NOT NULL AND lease_until IS NOT NULL)
         OR (state!='LEASED' AND token IS NULL AND lease_until IS NULL))
    );
    CREATE TABLE cancellation_recovery_events_v5 (
      id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES cancellation_jobs_v2(id),
      generation INTEGER NOT NULL, event TEXT NOT NULL, reason TEXT NOT NULL
    );
    CREATE TRIGGER recovery_events_no_update BEFORE UPDATE ON cancellation_recovery_events_v5
      BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
    CREATE TRIGGER recovery_events_no_delete BEFORE DELETE ON cancellation_recovery_events_v5
      BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
    ''')


def _audit(db, job_id, generation, event, reason):
    db.execute('INSERT INTO cancellation_recovery_events_v5(job_id,generation,event,reason) VALUES(?,?,?,?)',
               (job_id,generation,event,reason))


def seed_jobs(db):
    require_memory(db)
    if db.in_transaction: raise ContractError('open transaction')
    with db:
        db.execute('''INSERT INTO cancellation_recovery_v5(job_id)
          SELECT id FROM cancellation_jobs_v2 WHERE id NOT IN
          (SELECT job_id FROM cancellation_recovery_v5)''')


def claim(db, *, now, lease_seconds=30, max_attempts=4):
    require_memory(db)
    if db.in_transaction or type(now) is not int or lease_seconds < 1 or max_attempts < 1:
        raise ContractError('invalid claim')
    try:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('''SELECT r.job_id,r.generation,r.attempts FROM cancellation_recovery_v5 r
           WHERE ((r.state='PENDING' AND r.next_at<=?) OR
                  (r.state='LEASED' AND r.lease_until<=?)) AND r.attempts<?
           ORDER BY r.job_id LIMIT 1''',(now,now,max_attempts)).fetchone()
        if not row:
            db.execute('COMMIT');return None
        jid,gen,attempts=row
        token=secrets.token_hex(24)
        db.execute('''UPDATE cancellation_recovery_v5 SET state='LEASED',generation=?,token=?,
          lease_until=?,attempts=? WHERE job_id=?''',(gen+1,token,now+lease_seconds,attempts+1,jid))
        _audit(db,jid,gen+1,'CLAIM','offline lease')
        db.execute('COMMIT')
        return (jid,gen+1,token)
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise


def evaluate(db, claim_record, inventory, *, now, max_snapshot_age=10):
    """Evaluate one observation; no destructive action or torrent API request.

    PRESENT => RETRY regardless of freshness. ABSENT => DONE only with a fresh,
    matching observation. The caller-supplied snapshot is synthetic, not attested.
    """
    require_memory(db)
    if type(inventory) is not Inventory or type(now) is not int or max_snapshot_age < 0:
        raise ContractError('invalid observation')
    jid,gen,token=claim_record
    if db.in_transaction: raise ContractError('open transaction')
    try:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('''SELECT r.state,r.generation,r.token,r.lease_until,
           j.attempt_id,j.torrent_hash,d.series_id
           FROM cancellation_recovery_v5 r JOIN cancellation_jobs_v2 j ON j.id=r.job_id
           JOIN trial_decisions_v2 d ON d.id=j.decision_id WHERE r.job_id=?''',(jid,)).fetchone()
        if not row or row[:3]!=('LEASED',gen,token) or now>=row[3]:
            raise ContractError('stale or expired lease')
        _,_,_,_,aid,thash,sid=row
        attempt=db.execute('SELECT series_id,torrent_hash,status FROM download_attempts WHERE id=?',(aid,)).fetchone()
        if attempt is None or attempt[0]!=sid or attempt[1]!=thash or inventory.attempt_id!=aid or inventory.torrent_hash!=thash:
            state,reason='BLOCKED','attempt/hash/series mismatch'
        elif inventory.generation!=gen or inventory.observed_at>now or now-inventory.observed_at>max_snapshot_age:
            state,reason='PENDING','stale or wrong-generation inventory'
        elif not inventory.present:
            state,reason='DONE','synthetic inventory reports absent'
        else:
            state,reason='PENDING','torrent still present; no delete attempted'
        db.execute('''UPDATE cancellation_recovery_v5 SET state=?,token=NULL,lease_until=NULL,
          next_at=?,last_reason=? WHERE job_id=?''',(state,now+60,reason,jid))
        _audit(db,jid,gen,state,reason)
        db.execute('COMMIT')
        return state
    except BaseException:
        if db.in_transaction: db.execute('ROLLBACK')
        raise


def report(db):
    require_memory(db)
    return dict(db.execute('SELECT state,count(*) FROM cancellation_recovery_v5 GROUP BY state').fetchall())
