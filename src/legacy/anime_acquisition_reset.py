"""Series-scoped, explicit replay of completed verified acquisition notifications.

Reuses the *stored* Autobrr notification and immutable job payload. This is
not another Autobrr discovery, does not contact qBittorrent, and never purges
original source torrents or their ownership markers.
"""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from anime_acquisition_gate import approved_dispatch
from anime_identity_rejection_gate import resolve_notification

_HASH=re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_VIDEO={".mkv",".mp4",".m4v",".avi"}


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS series_acquisition_resets (
        id INTEGER PRIMARY KEY,
        series_id INTEGER NOT NULL REFERENCES series(id),
        created_at INTEGER NOT NULL,
        notification_ids_json TEXT NOT NULL,
        old_job_ids_json TEXT NOT NULL,
        new_job_ids_json TEXT NOT NULL,
        staged_files_removed INTEGER NOT NULL
    )""")


def _table_exists(db, name):
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _validate_record(nid, state, dispatch, token, payload_json,
                     infohash, tvdb, record_hash, staged_path, record_digest):
    if state!="DONE" or dispatch!="DONE" or token is not None:
        raise ValueError("Only fully completed, unleased acquisitions can be reset")
    payload=json.loads(payload_json)
    if not isinstance(payload,dict) or set(payload)!={
            "notification_id","infohash","magnet_uri","title","tvdb_id"}:
        raise ValueError("Stored acquisition payload invalid")
    magnet=payload["magnet_uri"]
    if (type(payload["notification_id"]) is not int or payload["notification_id"]!=nid
        or not isinstance(payload["infohash"],str)
        or payload["infohash"].lower()!=str(infohash).lower()
        or not _HASH.fullmatch(payload["infohash"].lower())
        or str(payload["tvdb_id"])!=str(tvdb)
        or not isinstance(payload["title"],str) or not payload["title"].strip()
        or not isinstance(magnet,str) or not magnet.startswith("magnet:?")):
        raise ValueError("Saved Autobrr notification does not match its verified job")
    xt=parse_qs(urlsplit(magnet).query).get("xt",[])
    if len(xt)!=1 or xt[0].lower()!="urn:btih:"+payload["infohash"].lower():
        raise ValueError("Saved torrent magnet does not match notification hash")
    if (not staged_path or not isinstance(record_hash,str)
        or record_hash.lower()!=payload["infohash"].lower()
        or not isinstance(record_digest,str) or
        not re.fullmatch(r"[0-9a-fA-F]{64}",record_digest)):
        raise ValueError("Missing or mismatched staged recovery evidence")


def _staged_files(db, rows, trial_root):
    """Validate *all* file targets before unlinking any one of them."""
    root=Path(trial_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Configured Anime-Trial root is missing or unsafe")
    root=root.resolve(strict=True)
    files=[]
    for row in rows:
        nid,season,episode,path_string,digest=row
        path=Path(path_string)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Unsafe staged media path")
        # Reject symlinked directories, even if they happen to resolve back in root.
        if path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise ValueError("Unsafe staged directory")
        if path.parent.parent.parent!=root:
            raise ValueError("Staged media must be inside a named series/season folder")
        if (path.parent.name!="Season %02d"%season or
            path.name!="S%02dE%02d"%(season,episode)+path.suffix.lower()
            or path.suffix.lower() not in _VIDEO):
            raise ValueError("Recovery record has unexpected staged media name")
        if db.execute("SELECT count(*) FROM torrent_recovery_records WHERE staged_path=?",
                      (path_string,)).fetchone()[0]!=1:
            raise ValueError("Staged media shared by multiple recovery records")
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError("Unsafe or missing staged media")
            h=hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1048576),b""):
                    h.update(chunk)
            if h.hexdigest().lower()!=digest.lower():
                raise ValueError("Staged file changed since verification; manual review required")
        nfo=path.with_suffix(".nfo")
        if nfo.is_symlink():
            raise ValueError("Unsafe staged episode metadata")
        files.append((path,nfo))
    return root,files


def reset_acquisitions(db, series_id, *, trial_root):
    """Delete this series' old DONE jobs, then replay saved verified work.

    This intentionally does not delete notifications, identity verification,
    approval evidence, qBittorrent state, ownership markers or other series.
    """
    if type(series_id) is not int or series_id<=0 or db.in_transaction:
        raise ValueError("Valid series ID and autocommit database required")
    if not isinstance(trial_root,(str,Path)) or not str(trial_root):
        raise ValueError("Trial root required")
    db.execute("BEGIN IMMEDIATE")
    try:
        series=db.execute("""SELECT source,status FROM series WHERE id=?""",
                          (series_id,)).fetchone()
        if not series or series[0]!="tvdb":
            raise ValueError("TVDB series not found")
        if series[1] in ("KEPT","SONARR_IMPORT_PENDING","REJECTED"):
            raise ValueError("Kept, importing or rejected series cannot be reset")
        if any(_table_exists(db,t) and db.execute(
                "SELECT 1 FROM "+t+" WHERE series_id=?",(series_id,)).fetchone()
                for t in ("sonarr_keep","sonarr_import_manifest",
                          "series_rejection_blocks","series_quarantine")):
            raise ValueError("Series has Sonarr handoff or rejected/quarantined status")
        rows=db.execute("""SELECT j.id,j.state,j.lease_token,j.payload_json,
                   d.notification_id,d.season,d.episode,d.state,
                   n.info_hash,v.tvdb_id,r.infohash,r.staged_path,r.sha256
            FROM episode_dispatch d
            JOIN daemon_jobs j ON j.kind='claimed_acquisition'
                AND j.subject_key=CAST(d.notification_id AS TEXT)
            JOIN notifications n ON n.id=d.notification_id
            JOIN verified_series_identity v ON v.notification_id=d.notification_id
            LEFT JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
            WHERE d.series_id=? ORDER BY d.notification_id""",(series_id,)).fetchall()
        if not rows:
            raise ValueError("No saved completed acquisitions to reset")
        missing=db.execute("""SELECT 1 FROM episode_dispatch d
            WHERE d.series_id=? AND NOT EXISTS
                (SELECT 1 FROM daemon_jobs j
                 WHERE j.kind='claimed_acquisition'
                   AND j.subject_key=CAST(d.notification_id AS TEXT))
            LIMIT 1""",(series_id,)).fetchone()
        if missing:
            raise ValueError("Series contains a dispatch without an acquisition job")
        if len(rows)>100:
            raise ValueError("Reset at most 100 episodes per series")
        paths=[]
        for jid,state,token,payload,nid,season,ep,dispatch,infohash,tvdb,rhash,staged,digest in rows:
            _validate_record(nid,state,dispatch,token,payload,infohash,tvdb,rhash,staged,digest)
            if resolve_notification(db,nid)!=series_id:
                raise ValueError("Notification no longer resolves to requested series")
            approval=db.execute("""SELECT decision,season,episode FROM episode_approval_queue
                WHERE notification_id=?""",(nid,)).fetchone()
            evidence=db.execute("""SELECT verified FROM episode_verification_v16
                WHERE notification_id=?""",(nid,)).fetchone()
            if (approval!=("AUTO_APPROVED",season,ep) or not evidence or evidence[0]!=1):
                raise ValueError("Stored episode approval evidence missing or changed")
            paths.append((nid,season,ep,staged,digest))
        # Unknown additional job references must be reviewed before destroying
        # a job. Known audit references are explicitly cleaned below.
        job_ids=[r[0] for r in rows]
        next_job_id=db.execute("SELECT COALESCE(MAX(id),0)+1 FROM daemon_jobs").fetchone()[0]
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if table in ("daemon_job_admin_events","daemon_job_archived_subjects") or not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*",table):
                continue
            if table=="daemon_job_cleanup_review":
                # An empty ledger cannot obstruct resetting unrelated DONE jobs.
                # Any ledger reference to a target job must instead block reset.
                if any(db.execute(
                    "SELECT 1 FROM daemon_job_cleanup_review WHERE job_id=?",
                    (jid,)).fetchone() for jid in job_ids):
                    raise ValueError("Canceled-job cleanup review blocks reset")
                continue
            if any(fk[2]=="daemon_jobs" for fk in db.execute('PRAGMA foreign_key_list("'+table+'")')):
                raise ValueError("Unknown job reference in "+table+"; reset refused")
        root,files=_staged_files(db,paths,trial_root)
        # Hold SQLite's write lock throughout deletion and recreation; workers
        # cannot claim any new job in the middle of the reset.
        removed=0
        for path,nfo in files:
            if path.exists():
                path.unlink()
                removed+=1
            if nfo.is_file() and not nfo.is_symlink():
                nfo.unlink()
        # Only prune directories when they contain nothing but optional NFO.
        for folder in sorted({p.parent.parent for p,_ in files},key=str):
            for season_dir in sorted({p.parent for p,_ in files if p.parent.parent==folder},key=str):
                try:
                    season_dir.rmdir()
                except OSError:
                    pass
            show_nfo=folder/"tvshow.nfo"
            if (show_nfo.is_file() and not show_nfo.is_symlink()
                and set(folder.iterdir())=={show_nfo}):
                show_nfo.unlink()
            try:
                folder.rmdir()
            except OSError:
                pass
        ensure_schema(db)
        for jid in job_ids:
            if _table_exists(db,"daemon_job_archived_subjects"):
                db.execute("DELETE FROM daemon_job_archived_subjects WHERE job_id=?",(jid,))
            if _table_exists(db,"daemon_job_admin_events"):
                db.execute("DELETE FROM daemon_job_admin_events WHERE job_id=?",(jid,))
            db.execute("DELETE FROM daemon_jobs WHERE id=? AND state='DONE'",(jid,))
        notification_ids=[]
        fresh_ids=[]
        for jid,state,token,payload,nid,season,ep,dispatch,infohash,tvdb,rhash,staged,digest in rows:
            notification_ids.append(nid)
            db.execute("DELETE FROM torrent_recovery_records WHERE notification_id=?",(nid,))
            db.execute("""UPDATE episode_dispatch SET state='CLAIMED',last_error=NULL,
                attempts=0,updated_at=? WHERE notification_id=?""",(int(time.time()),nid))
            # Re-verify authorization using the exact original notification.
            approved_dispatch(db,nid)
            db.execute("""UPDATE episodes SET status='ACQUIRING'
                WHERE series_id=? AND season=? AND episode=?""",(series_id,season,ep))
            fresh=next_job_id+len(fresh_ids)
            db.execute("""INSERT INTO daemon_jobs
                (id,kind,subject_key,payload_json,state,available_at,attempts)
                VALUES (?,'claimed_acquisition',?,?,'READY',0,0)""",
                (fresh,str(nid),payload))
            fresh_ids.append(fresh)
        db.execute("""INSERT INTO series_acquisition_resets
            (series_id,created_at,notification_ids_json,old_job_ids_json,
             new_job_ids_json,staged_files_removed)
            VALUES (?,?,?,?,?,?)""",
            (series_id,int(time.time()),json.dumps(notification_ids),
             json.dumps(job_ids),json.dumps(fresh_ids),removed))
        db.execute("""UPDATE series SET status='DISCOVERED' WHERE id=?""",(series_id,))
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key failure after reset")
        db.commit()
        return {"ok":True,"series_id":series_id,"removed_completed_jobs":len(job_ids),
                "requeued_jobs":len(fresh_ids),"removed_staged_files":removed,
                "notifications_reused":notification_ids,"new_job_ids":fresh_ids,
                "original_torrents_preserved":True}
    except BaseException:
        db.rollback()
        raise
