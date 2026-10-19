"""Read-only inspection of dispatch claims for recovery planning.

This module never resets claims automatically. Operators can inspect stale
claims before deciding whether an external action needs reconciliation.
"""
import time

def stale_claims(db, *, older_than_seconds=3600, now=None, limit=100):
    if type(older_than_seconds) is not int or older_than_seconds<60:
        raise ValueError("Invalid age threshold")
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError("Invalid limit")
    if db.in_transaction:
        raise ValueError("Read-only inspection requires autocommit")
    now=time.time() if now is None else now
    rows=db.execute("""SELECT notification_id,series_id,season,episode,
                              attempts,updated_at
                       FROM episode_dispatch
                       WHERE state='CLAIMED' AND updated_at<=?
                       ORDER BY updated_at,notification_id LIMIT ?""",
                    (int(now-older_than_seconds),limit)).fetchall()
    return [dict(zip(("notification_id","series_id","season","episode",
                      "attempts","updated_at"),row)) for row in rows]
