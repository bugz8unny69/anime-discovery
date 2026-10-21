"""Explicit, resumable canceled-job torrent cleanup (never deletes media files).

Rechecks durable attribution and active consumers on every attempt. A missing
qB record is not treated as proof that this application removed it.
"""
import json
import sqlite3
import time

from anime_qb_ownership import CATEGORY

def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def prepare(db, job_id):
    """Read-only, fail-closed preview for an archived canceled job."""
    if type(job_id) is not int or job_id < 1:
        raise ValueError("Invalid job id")
    tabs=_tables(db)
    required={"daemon_jobs","daemon_job_archived_subjects","daemon_job_cleanup_review",
              "qb_torrent_ownership"}
    if not required <= tabs:
        raise ValueError("Cleanup evidence unavailable")
    row=db.execute("""SELECT j.state,a.kind,a.original_subject_key,
        c.candidate_hashes_json FROM daemon_jobs j
        JOIN daemon_job_archived_subjects a ON a.job_id=j.id
        JOIN daemon_job_cleanup_review c ON c.job_id=j.id WHERE j.id=?""",
        (job_id,)).fetchone()
    if not row or row[0]!="BLOCKED":
        raise ValueError("Only canceled jobs can request cleanup")
    _,kind,subject,raw=row
    hashes=json.loads(raw)
    if not isinstance(hashes,list) or not all(isinstance(h,str) for h in hashes):
        raise ValueError("Invalid cleanup evidence")
    records=[]
    for h in hashes:
        if len(h) not in (40,64) or any(ch not in "0123456789abcdef" for ch in h):
            raise ValueError("Invalid cleanup candidate")
        owned=db.execute("""SELECT status,marker,category FROM qb_torrent_ownership
            WHERE infohash=?""",(h,)).fetchone()
        shared=False
        if "notifications" in tabs:
            shared=bool(db.execute("""SELECT 1 FROM notifications
                WHERE lower(info_hash)=? AND CAST(id AS TEXT)!=? LIMIT 1""",
                (h,subject)).fetchone())
        if "torrent_recovery_records" in tabs:
            shared=bool(db.execute("""SELECT 1 FROM torrent_recovery_records
                WHERE lower(infohash)=? AND CAST(notification_id AS TEXT) != ?
                LIMIT 1""",(h,subject)).fetchone())
        if "anime_batch_authorizations" in tabs:
            shared=shared or bool(db.execute("""SELECT 1 FROM anime_batch_authorizations
                WHERE lower(infohash)=? AND CAST(notification_id AS TEXT) != ?
                LIMIT 1""",(h,subject)).fetchone())
        # Missing provenance tables mean sharing cannot be ruled out.
        proven=(owned is not None and owned[0]=="OWNED" and
                owned[2]==CATEGORY and bool(owned[1]))
        eligible=(proven and not shared and
                  {"notifications","torrent_recovery_records","anime_batch_authorizations"} <= tabs)
        records.append({"infohash":h,"eligible":eligible,"shared":shared,
                        "ownership":owned[0] if owned else "UNCERTAIN"})
    return {"job_id":job_id,"records":records,
            "can_remove_torrents":bool(records) and all(r["eligible"] for r in records),
            "will_delete_files":False}

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_job_cleanup_attempts (
        job_id INTEGER NOT NULL REFERENCES daemon_jobs(id), infohash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('PENDING','UNCERTAIN','REMOVED')),
        updated_at REAL NOT NULL, PRIMARY KEY(job_id,infohash))""")

def cleanup_torrents(db,job_id,qb,*,approved=False):
    """Operator-only qB cleanup. Never request deleteFiles, never unlink files.

    A qB timeout after removal is marked UNCERTAIN; an operator must inspect
    before retrying. Does not initiate cleanup from worker or cancel actions.
    """
    if approved is not True:
        raise PermissionError("Explicit cleanup approval required")
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    preview=prepare(db,job_id)
    if not preview["can_remove_torrents"]:
        raise ValueError("Unknown ownership or shared torrent; cleanup refused")
    ensure_schema(db)
    results=[]
    for record in preview["records"]:
        h=record["infohash"]
        prior=db.execute("""SELECT state FROM daemon_job_cleanup_attempts
            WHERE job_id=? AND infohash=?""",(job_id,h)).fetchone()
        if prior and prior[0]=="REMOVED":
            results.append((h,"REMOVED"))
            continue
        if prior and prior[0]=="UNCERTAIN":
            raise ValueError("Prior removal outcome uncertain; manual verification required")
        current=qb.torrent_identity(h)
        ownership=db.execute("""SELECT status,marker,category FROM qb_torrent_ownership
            WHERE infohash=?""",(h,)).fetchone()
        tags=current.get("tags","") if isinstance(current,dict) else ""
        tags={s.strip() for s in tags.split(",")} if isinstance(tags,str) else set()
        if (not isinstance(current,dict) or current.get("hash","").lower()!=h or
            not ownership or ownership[0]!="OWNED" or
            ownership[2]!=CATEGORY or ownership[1] not in tags or
            current.get("category")!=CATEGORY):
            raise ValueError("Current torrent ownership cannot be verified")
        # Recheck other consumers immediately before submitting removal.
        if not all(r["eligible"] for r in prepare(db,job_id)["records"]):
            raise ValueError("Torrent became shared or ownership changed")
        db.execute("""INSERT INTO daemon_job_cleanup_attempts VALUES (?,?,'UNCERTAIN',?)
            ON CONFLICT(job_id,infohash) DO UPDATE SET state='UNCERTAIN',
            updated_at=excluded.updated_at""",(job_id,h,time.time()))
        try:
            qb.remove_torrent(h,delete_files=False)
            if qb.torrent_identity(h) is not None:
                raise RuntimeError("Torrent removal not confirmed")
        except Exception:
            # Cannot know if qB completed a timed-out request.
            raise
        db.execute("""UPDATE daemon_job_cleanup_attempts SET state='REMOVED',
            updated_at=? WHERE job_id=? AND infohash=?""",(time.time(),job_id,h))
        results.append((h,"REMOVED"))
    return results
