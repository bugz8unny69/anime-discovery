"""Persistent idempotency reservations for external operations."""
import time
import uuid

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS external_actions (
        action_type TEXT NOT NULL,
        action_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        state TEXT NOT NULL,
        token TEXT NOT NULL,
        result_ref TEXT,
        updated_at REAL NOT NULL,
        PRIMARY KEY(action_type,action_key))""")

def reserve(db, action_type, action_key, fingerprint):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    if not all(isinstance(x,str) and x for x in (action_type,action_key,fingerprint)):
        raise ValueError("Missing action identity")
    token=uuid.uuid4().hex
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        old=db.execute("SELECT state,fingerprint FROM external_actions WHERE action_type=? AND action_key=?",
                       (action_type,action_key)).fetchone()
        if old:
            if old[1]!=fingerprint:
                raise ValueError("Conflicting external request")
            db.commit()
            return None
        db.execute("INSERT INTO external_actions VALUES (?,?,?,'RESERVED',?,NULL,?)",
                   (action_type,action_key,fingerprint,token,time.time()))
        db.commit()
        return token
    except BaseException:
        db.rollback()
        raise

def transition(db, action_type, action_key, token, old_state, new_state, result_ref=None):
    if (old_state,new_state) not in (("RESERVED","UNCERTAIN"),("UNCERTAIN","CONFIRMED")):
        raise ValueError("Unsupported action transition")
    if new_state=="CONFIRMED" and not result_ref:
        raise ValueError("Confirmed operation requires external reference")
    if db.in_transaction:
        raise ValueError("Autocommit required")
    db.execute("BEGIN IMMEDIATE")
    try:
        changed=db.execute("""UPDATE external_actions
            SET state=?,result_ref=?,updated_at=?
            WHERE action_type=? AND action_key=? AND token=? AND state=?""",
            (new_state,result_ref,time.time(),action_type,action_key,token,old_state))
        if changed.rowcount!=1:
            raise ValueError("Stale or invalid action transition")
        db.commit()
    except BaseException:
        db.rollback()
        raise
