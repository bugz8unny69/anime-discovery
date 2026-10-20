"""Finalize acquired episodes only under an active daemon lease.

Called after staged media and a durable recovery record have been verified.
"""
import time
from anime_acquisition_gate import approved_dispatch
from anime_series_naming import clean_series_name

def finalize_acquisition(db, job_id, lease_token, notification_id, *, series_title=None, now=None):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    now=time.time() if now is None else now
    db.execute("BEGIN IMMEDIATE")
    try:
        lease=db.execute("""SELECT state,lease_token,lease_until,kind,subject_key
            FROM daemon_jobs WHERE id=?""",(job_id,)).fetchone()
        if (not lease or lease[0]!="LEASED" or lease[1]!=lease_token or
                lease[2]<now or lease[3]!="claimed_acquisition" or
                lease[4]!=str(notification_id)):
            raise ValueError("Stale acquisition lease")
        approved_dispatch(db,notification_id)
        record=db.execute("""SELECT staged_path,sha256 FROM torrent_recovery_records
            WHERE notification_id=?""",(notification_id,)).fetchone()
        if not record or not record[0] or not record[1]:
            raise ValueError("Missing durable recovery record")
        updated=db.execute("""UPDATE episode_dispatch SET state='DONE',
            last_error=NULL,updated_at=?
            WHERE notification_id=? AND state='CLAIMED'""",
            (int(now),notification_id))
        if updated.rowcount!=1:
            raise ValueError("Dispatch changed during finalization")
        if series_title is not None:
            name=clean_series_name(series_title)
            db.execute("""UPDATE series SET title=? WHERE id=(
                SELECT series_id FROM episode_dispatch WHERE notification_id=?)""",
                (name,notification_id))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodes'").fetchone():
            db.execute("""UPDATE episodes SET status='STAGED'
                WHERE (series_id,season,episode) IN (
                    SELECT series_id,season,episode FROM episode_dispatch
                    WHERE notification_id=?)""",(notification_id,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
