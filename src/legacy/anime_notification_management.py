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
