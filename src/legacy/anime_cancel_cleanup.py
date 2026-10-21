"""Explicit, resumable canceled-job torrent cleanup with optional guarded downloads.

Rechecks durable attribution and active consumers on every attempt. A missing
qB record is not treated as proof that this application removed it.
"""
import json
import sqlite3
from pathlib import Path
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
            shared=shared or bool(db.execute("""SELECT 1 FROM torrent_recovery_records
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

def preview_live(db,job_id,qb,*,download_root=None,trial_root=None,sonarr_root=None):
    """Read-only live preflight; no archive, SQLite or filesystem writes."""
    result=prepare(db,job_id)
    for record in result["records"]:
        record["live_owned"]=False
        record["file_cleanup_ready"]=False
        record["file_preview"]=[]
        record["file_bytes"]=0
        if not record["eligible"]:
            continue
        h=record["infohash"]
        previous=None
        if "daemon_job_cleanup_attempts" in _tables(db):
            previous=db.execute("""SELECT state,delete_files_requested,file_paths_json
                FROM daemon_job_cleanup_attempts WHERE job_id=? AND infohash=?""",
                (job_id,h)).fetchone()
        record["retry_state"]=previous[0] if previous else None
        record["reconcile_only"]=False
        owned=db.execute("""SELECT marker,category FROM qb_torrent_ownership
            WHERE infohash=? AND status='OWNED'""",(h,)).fetchone()
        current=qb.torrent_identity(h)
        if previous and previous[0] in ("UNCERTAIN","REMOVED","ABSENT") and current is None:
            # There is no torrent to delete again. An earlier UNCERTAIN
            # request may be reconciled by explicit operator confirmation.
            record["reconcile_only"]=True
            record["file_cleanup_ready"]=bool(previous[1])
            record["file_preview"]=json.loads(previous[2])
            continue
        tags=current.get("tags","") if isinstance(current,dict) else ""
        labels={v.strip() for v in tags.split(",")} if isinstance(tags,str) else set()
        if (not owned or not isinstance(current,dict) or
            current.get("hash","").lower()!=h or
            current.get("category")!=CATEGORY or
            owned[1]!=CATEGORY or owned[0] not in labels):
            record["eligible"]=False
            continue
        record["live_owned"]=True
        if download_root and trial_root:
            try:
                from anime_cleanup_file_safety import preflight
                files=preflight(qb,h,download_root=download_root,
                    trial_root=trial_root,sonarr_root=sonarr_root)
            except (OSError,ValueError,RuntimeError):
                pass
            else:
                record["file_cleanup_ready"]=True
                record["file_preview"]=files["files"]
                record["file_bytes"]=files["bytes"]
    result["can_remove_torrents"]=bool(result["records"]) and all(
        r["eligible"] for r in result["records"])
    result["can_delete_download_files"]=result["can_remove_torrents"] and all(
        r["file_cleanup_ready"] for r in result["records"])
    result["possible_download_bytes"]=sum(r["file_bytes"] for r in result["records"])
    return result

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS daemon_job_cleanup_attempts (
        job_id INTEGER NOT NULL REFERENCES daemon_jobs(id), infohash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('PENDING','UNCERTAIN','REMOVED','ABSENT')),
        updated_at REAL NOT NULL,
        delete_files_requested INTEGER NOT NULL DEFAULT 0,
        file_paths_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY(job_id,infohash))""")

def cleanup_torrents(db,job_id,qb,*,approved=False,delete_download_files=False,
                     download_root=None,trial_root=None,sonarr_root=None):
    """Operator-only qB cleanup; downloads require full preflight and opt-in.

    A qB timeout is marked UNCERTAIN; reconciliation must not resend a
    destructive request without checking current identity. Staged files
    are outside this function's authorized scope.
    """
    if approved is not True:
        raise PermissionError("Explicit cleanup approval required")
    if type(delete_download_files) is not bool:
        raise ValueError("File cleanup must be an explicit boolean")
    if delete_download_files and (not download_root or not trial_root):
        raise ValueError("Download cleanup requires verified storage roots")
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    preview=prepare(db,job_id)
    if not preview["can_remove_torrents"]:
        raise ValueError("Unknown ownership or shared torrent; cleanup refused")
    ensure_schema(db)
    results=[]
    for record in preview["records"]:
        h=record["infohash"]
        prior=db.execute("""SELECT state,delete_files_requested,file_paths_json
            FROM daemon_job_cleanup_attempts WHERE job_id=? AND infohash=?""",
            (job_id,h)).fetchone()
        if prior and prior[0] in ("REMOVED","ABSENT"):
            if prior[1] and any(Path(path).exists() or Path(path).is_symlink()
                                for path in json.loads(prior[2])):
                raise ValueError("Files remain after earlier cleanup; manual review required")
            results.append((h,"ALREADY_"+prior[0]))
            continue
        if prior and prior[0]=="UNCERTAIN" and bool(prior[1])!=delete_download_files:
            raise ValueError("Cannot change cleanup mode while prior attempt is uncertain")
        current=qb.torrent_identity(h)
        if prior and prior[0]=="UNCERTAIN" and current is None:
            # A previous request may have completed despite a lost reply.
            # Record verified absence without asserting who removed it.
            db.execute("""UPDATE daemon_job_cleanup_attempts SET state='ABSENT',
                updated_at=? WHERE job_id=? AND infohash=?""",(time.time(),job_id,h))
            remaining=bool(prior[1]) and any(
                (Path(path).exists() or Path(path).is_symlink())
                for path in json.loads(prior[2]))
            results.append((h,"FILES_REMAIN" if remaining else "ABSENT"))
            continue
        if prior and prior[0]=="UNCERTAIN":
            # A hash still present after an ambiguous request might be a new
            # torrent, or qB might not have acted. Never resend deletion.
            raise ValueError("Prior cleanup outcome uncertain; manual verification required")
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
        plan={"files":[],"bytes":0}
        if delete_download_files:
            from anime_cleanup_file_safety import preflight
            plan=preflight(qb,h,download_root=download_root,trial_root=trial_root,
                           sonarr_root=sonarr_root)
        db.execute("""INSERT INTO daemon_job_cleanup_attempts
            (job_id,infohash,state,updated_at,delete_files_requested,file_paths_json)
            VALUES (?,?,'UNCERTAIN',?,?,?)
            ON CONFLICT(job_id,infohash) DO UPDATE SET state='UNCERTAIN',
            updated_at=excluded.updated_at,
            delete_files_requested=excluded.delete_files_requested,
            file_paths_json=excluded.file_paths_json""",
            (job_id,h,time.time(),int(delete_download_files),
             json.dumps(plan["files"])))
        db.execute("""UPDATE daemon_job_cleanup_review SET status='CLEANUP_NEEDED'
            WHERE job_id=?""",(job_id,))
        # Fence new notifications/authorizations while executing the
        # externally destructive step. UNCERTAIN was already committed, so
        # interruption or rollback never erases the recovery checkpoint.
        db.execute("BEGIN IMMEDIATE")
        try:
            if not all(r["eligible"] for r in prepare(db,job_id)["records"]):
                raise ValueError("Torrent became shared before cleanup")
            live=qb.torrent_identity(h)
            fresh_tags=live.get("tags","") if isinstance(live,dict) else ""
            fresh_labels={v.strip() for v in fresh_tags.split(",")} if isinstance(fresh_tags,str) else set()
            if (not isinstance(live,dict) or live.get("hash","").lower()!=h or
                live.get("category")!=CATEGORY or ownership[1] not in fresh_labels):
                raise ValueError("Torrent identity changed before cleanup")
            if delete_download_files:
                from anime_cleanup_file_safety import preflight
                fresh_plan=preflight(qb,h,download_root=download_root,
                    trial_root=trial_root,sonarr_root=sonarr_root)
                if fresh_plan!=plan:
                    raise ValueError("Torrent download manifest changed before cleanup")
            qb.remove_torrent(h,delete_files=delete_download_files)
            if qb.torrent_identity(h) is not None:
                raise RuntimeError("Torrent removal not confirmed")
            if delete_download_files and any(
                    Path(path).exists() or Path(path).is_symlink()
                    for path in plan["files"]):
                raise RuntimeError("Downloaded file removal not confirmed")
            db.execute("""UPDATE daemon_job_cleanup_attempts SET state='REMOVED',
                updated_at=? WHERE job_id=? AND infohash=?""",(time.time(),job_id,h))
            db.commit()
        except BaseException:
            db.rollback()
            # Original UNCERTAIN checkpoint survives a lost qB response.
            raise
        results.append((h,"REMOVED"))
    if len(results)==len(preview["records"]) and all(
            state in ("REMOVED","ABSENT","ALREADY_REMOVED","ALREADY_ABSENT")
            for _,state in results):
        modes=db.execute("""SELECT delete_files_requested,file_paths_json
            FROM daemon_job_cleanup_attempts WHERE job_id=?""",(job_id,)).fetchall()
        files_cleared=bool(modes) and all(
            requested and all(not Path(path).exists() and not Path(path).is_symlink()
                              for path in json.loads(paths))
            for requested,paths in modes)
        status=("DOWNLOADS_CLEARED" if files_cleared else
                "CLEANUP_NEEDED" if any(requested for requested,_ in modes)
                else "TORRENTS_REMOVED")
        db.execute("""UPDATE daemon_job_cleanup_review SET status=?
            WHERE job_id=?""",(status,job_id))
    return results

def cleanup_rejected_dual_audio(db,job,infohash,qb,*,download_root,trial_root,sonarr_root=None):
    """Automated cleanup ONLY after a confirmed failed JP+EN media probe.

    Reuses existing qB ownership markers and file-safety preflight. A durable
    UNCERTAIN checkpoint is written before destructive I/O. Unknown outcomes
    retain the episode slot for manual reconciliation, never auto-failover.
    """
    from anime_cleanup_file_safety import preflight
    from anime_qb_ownership import CATEGORY
    from anime_episode_acquisition_guard import ensure_schema as slot_schema
    if db.in_transaction:
        raise ValueError("Cleanup requires autocommit")
    if type(job.get("id")) is not int or type(job.get("lease_token")) is not str:
        raise ValueError("Active acquisition job lease required")
    nid=job.get("notification_id")
    if type(nid) is not int or nid<1:
        raise ValueError("Verified notification required")
    stamp=time.time()
    tabs=_tables(db)
    if not {"notifications","episode_dispatch","torrent_recovery_records",
            "anime_batch_authorizations","qb_torrent_ownership","daemon_jobs"} <= tabs:
        raise ValueError("Incomplete cleanup provenance")
    lease=db.execute("""SELECT state,lease_token,lease_until,kind,subject_key
        FROM daemon_jobs WHERE id=?""",(job["id"],)).fetchone()
    if not lease or lease[0]!="LEASED" or lease[1]!=job["lease_token"] or lease[2]<stamp or lease[3]!="claimed_acquisition" or lease[4]!=str(nid):
        raise ValueError("Cleanup job lease changed")
    source=db.execute("SELECT lower(info_hash) FROM notifications WHERE id=?",(nid,)).fetchone()
    if not source or source[0]!=infohash:
        raise ValueError("Cleanup hash disagrees with notification")
    if db.execute("SELECT 1 FROM torrent_recovery_records WHERE notification_id=?",(nid,)).fetchone():
        raise ValueError("Staged media must never be cleaned as rejected audio")
    if db.execute("SELECT 1 FROM notifications WHERE lower(info_hash)=? AND id<>?",(infohash,nid)).fetchone():
        raise ValueError("Shared release hash")
    if db.execute("SELECT 1 FROM torrent_recovery_records WHERE lower(infohash)=? AND notification_id<>?",(infohash,nid)).fetchone():
        raise ValueError("Shared staged torrent")
    if db.execute("SELECT 1 FROM anime_batch_authorizations WHERE lower(infohash)=? AND notification_id<>?",(infohash,nid)).fetchone():
        raise ValueError("Shared batch torrent")
    owner=db.execute("SELECT status,marker,category FROM qb_torrent_ownership WHERE infohash=?",(infohash,)).fetchone()
    if not owner or owner[0]!="OWNED" or owner[2]!=CATEGORY or not owner[1]:
        raise ValueError("Torrent ownership not proven")
    slot_schema(db)
    slot=db.execute("""SELECT 1 FROM anime_episode_acquisition_slots
        WHERE owner_notification_id=? AND state='ACTIVE'""",(nid,)).fetchone()
    if not slot:
        raise ValueError("Rejected release does not own an active episode")
    ensure_schema(db)
    db.execute("""CREATE TABLE IF NOT EXISTS anime_rejected_audio_cleanup (
        job_id INTEGER PRIMARY KEY, infohash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('UNCERTAIN','REMOVED')),
        paths_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
    if db.execute("SELECT 1 FROM anime_rejected_audio_cleanup WHERE job_id=?",(job["id"],)).fetchone():
        raise ValueError("Prior audio cleanup outcome requires reconciliation")
    # qB mutation is allowed only after durable ownership is established.
    qb.stop_owned_torrent(infohash)
    plan=preflight(qb,infohash,download_root=download_root,
                   trial_root=trial_root,sonarr_root=sonarr_root)
    if not plan["files"]:
        raise ValueError("No verified torrent payload paths")
    db.execute("BEGIN IMMEDIATE")
    try:
        # Fence new leases and any new sharing link before destructive I/O.
        live_lease=db.execute("""SELECT lease_token,lease_until,state FROM daemon_jobs
            WHERE id=?""",(job["id"],)).fetchone()
        if not live_lease or live_lease[0]!=job["lease_token"] or live_lease[1]<time.time() or live_lease[2]!="LEASED":
            raise ValueError("Cleanup lease expired before deletion")
        if db.execute("SELECT 1 FROM torrent_recovery_records WHERE lower(infohash)=?",(infohash,)).fetchone():
            raise ValueError("Torrent acquired staged-media consumer")
        if db.execute("SELECT 1 FROM anime_batch_authorizations WHERE lower(infohash)=?",(infohash,)).fetchone():
            raise ValueError("Torrent acquired batch consumer")
        if db.execute("SELECT 1 FROM notifications WHERE lower(info_hash)=? AND id<>?",(infohash,nid)).fetchone():
            raise ValueError("Torrent became shared")
        current=qb.torrent_identity(infohash)
        tags={t.strip() for t in str((current or {}).get("tags") or "").split(",")}
        if (not current or current.get("hash","").lower()!=infohash or
            current.get("category")!=CATEGORY or owner[1] not in tags):
            raise ValueError("Torrent ownership changed")
        if preflight(qb,infohash,download_root=download_root,
                     trial_root=trial_root,sonarr_root=sonarr_root)!=plan:
            raise ValueError("Torrent payload changed")
        db.execute("""INSERT INTO anime_rejected_audio_cleanup
            VALUES (?,?,'UNCERTAIN',?,?)""",
            (job["id"],infohash,json.dumps(plan["files"]),time.time()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    # An error after UNCERTAIN is intentionally not retried automatically.
    qb.remove_torrent(infohash,delete_files=True)
    if qb.torrent_identity(infohash) is not None:
        raise RuntimeError("qBittorrent removal not confirmed")
    if any(Path(path).exists() or Path(path).is_symlink() for path in plan["files"]):
        raise RuntimeError("Torrent payload deletion not confirmed")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""UPDATE anime_rejected_audio_cleanup SET state='REMOVED',
            updated_at=? WHERE job_id=? AND state='UNCERTAIN'""",
            (time.time(),job["id"]))
        key=db.execute("""SELECT tvdb_id,season,episode FROM anime_episode_acquisition_slots
            WHERE owner_notification_id=? AND state='ACTIVE'""",(nid,)).fetchone()
        if not key:
            raise ValueError("Active episode claim not found after cleanup")
        changed=db.execute("""DELETE FROM anime_episode_acquisition_slots
            WHERE owner_notification_id=? AND state='ACTIVE'""",(nid,)).rowcount
        db.execute("""UPDATE daemon_jobs SET available_at=0
            WHERE kind='claimed_acquisition' AND state='DEFERRED'
              AND last_error='ON_HOLD' AND subject_key IN (
                SELECT CAST(d.notification_id AS TEXT) FROM episode_dispatch d
                JOIN series se ON se.id=d.series_id
                WHERE se.source='tvdb' AND se.external_id=?
                  AND d.season=? AND d.episode=?
              )""",key)
        if changed!=1:
            raise ValueError("Episode claim changed during cleanup")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return True
