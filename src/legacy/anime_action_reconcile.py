"""Read-only reconciliation of uncertain external actions.

The caller supplies an authoritative lookup function. This module never
submits or repeats an external operation.
"""
from anime_external_actions import ensure_schema

def reconcile(db, action_type, action_key, fingerprint, lookup):
    """Resolve only confirmed external outcomes.

    lookup(action_type, action_key) returns an external result reference or
    None. None leaves the action UNCERTAIN for another scheduled check.
    """
    if db.in_transaction:
        raise ValueError("Autocommit required")
    ensure_schema(db)
    row=db.execute("""SELECT state,fingerprint,token,result_ref FROM external_actions
        WHERE action_type=? AND action_key=?""",(action_type,action_key)).fetchone()
    if row is None:
        raise ValueError("Action not reserved")
    state, stored, token, result=row
    if stored!=fingerprint:
        raise ValueError("Conflicting request")
    if state=="CONFIRMED":
        return result
    if state!="UNCERTAIN":
        return None
    # External lookup must be read-only. Do not hold a SQLite write lock
    # while making the network request.
    found=lookup(action_type,action_key)
    if not found:
        return None
    from anime_external_actions import transition
    transition(db,action_type,action_key,token,"UNCERTAIN","CONFIRMED",str(found))
    return str(found)
