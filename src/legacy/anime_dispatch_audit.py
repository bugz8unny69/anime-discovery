"""Read-only audit of acquisition prerequisites in a migrated database.

Does not enqueue, submit, stage, delete, or mutate anything.
"""
from anime_acquisition_gate import approved_dispatch

def audit_claimed(db, notification_id):
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    try:
        approval=approved_dispatch(db,notification_id)
    except (ValueError,LookupError) as exc:
        return {"authorized":False,"reason":type(exc).__name__}
    row=db.execute("SELECT info_hash FROM notifications WHERE id=?",(notification_id,)).fetchone()
    if row is None or not isinstance(row[0],str):
        return {"authorized":False,"reason":"MISSING_INFOHASH"}
    infohash=row[0].lower()
    if len(infohash) not in (40,64) or any(c not in "0123456789abcdef" for c in infohash):
        return {"authorized":False,"reason":"INVALID_INFOHASH"}
    return {"authorized":True,"series_id":approval["series_id"],
            "season":approval["season"],"episode":approval["episode"],
            "infohash":infohash}
