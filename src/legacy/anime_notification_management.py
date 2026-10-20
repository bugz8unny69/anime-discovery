"""Safe deletion of intake-only notifications, never torrent/media cleanup."""
import sqlite3

AUXILIARY={"ntfy_delivery","unified_identity_checks","shoko_alert_delivery"}

def delete_unmatched(db, notification_id):
    try:
        nid=int(notification_id)
    except (ValueError,TypeError):
        raise ValueError("Invalid notification ID") from None
    if nid<1 or db.in_transaction:
        raise ValueError("Deletion needs a valid ID and autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT status FROM notifications WHERE id=?",(nid,)).fetchone()
        if row is None:
            raise ValueError("Notification not found")
        if row[0] not in ("NEEDS_REVIEW","UNTRUSTED","RECEIVED","IDENTIFYING"):
            raise ValueError("Only unmatched intake may be deleted")
        if db.execute("SELECT 1 FROM daemon_jobs WHERE subject_key=? LIMIT 1",(str(nid),)).fetchone():
            raise ValueError("Acquisition job exists; deletion refused")
        # Fail closed on every notification foreign-key relationship we don't
        # explicitly recognize as disposable metadata.
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if not table.replace("_","").isalnum():
                continue
            for fk in db.execute('PRAGMA foreign_key_list("'+table+'")'):
                if fk[2]!="notifications":
                    continue
                column=fk[3]
                if not column.replace("_","").isalnum():
                    raise ValueError("Unexpected relation to notification")
                exists=db.execute('SELECT 1 FROM "'+table+'" WHERE "'+column+'"=? LIMIT 1',(nid,)).fetchone()
                if not exists:continue
                if table not in AUXILIARY:
                    raise ValueError("Related records exist in "+table+"; deletion refused")
                db.execute('DELETE FROM "'+table+'" WHERE "'+column+'"=?',(nid,))
        db.execute("DELETE FROM notifications WHERE id=?",(nid,))
        db.commit()
        return {"deleted":True,"notification_id":nid}
    except BaseException:
        db.rollback()
        raise


def recheck_unmatched_identity(db, notification_id):
    """Explicitly re-run trusted provider triage for a terminal intake review.

    Cannot turn an already dispatched/authorized notification into a new
    acquisition. No media, torrent, or historical evidence is removed. The
    existing identity monitor performs the work on its next iteration.
    """
    try:
        nid=int(notification_id)
    except (ValueError,TypeError):
        raise ValueError("Valid notification ID required") from None
    if nid<=0 or db.in_transaction:
        raise ValueError("Identity recheck requires positive ID and autocommit")
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT status FROM notifications WHERE id=?",(nid,)).fetchone()
        if not row or row[0]!="NEEDS_REVIEW":
            raise ValueError("Only terminal unapproved identity reviews can be rechecked")
        for table in ("daemon_jobs","episode_dispatch","verified_series_identity",
                      "anime_batch_authorizations"):
            present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (table,)).fetchone()
            if not present:
                continue
            column="id" if table=="daemon_jobs" else "notification_id"
            if table=="daemon_jobs":
                exists=db.execute("SELECT 1 FROM daemon_jobs WHERE subject_key=?",
                                  (str(nid),)).fetchone()
            else:
                exists=db.execute("SELECT 1 FROM "+table+" WHERE "+column+"=?",
                                  (nid,)).fetchone()
            if exists:
                raise ValueError("Identity review already has authorized or dispatched work")
        changed=db.execute("""UPDATE notifications SET status='IDENTIFYING'
                             WHERE id=? AND status='NEEDS_REVIEW'""",(nid,)).rowcount
        if changed!=1:
            raise ValueError("Identity review state changed")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_identity_checks'").fetchone():
            db.execute("UPDATE unified_identity_checks SET next_at=0 WHERE notification_id=?",(nid,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"notification_id":nid,"status":"IDENTIFYING","queued":False,
            "message":"Identity recheck scheduled; acquisition remains blocked until provider verification"}
