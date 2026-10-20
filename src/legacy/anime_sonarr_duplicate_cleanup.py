"""Explicitly approved cleanup of redundant Anime-Trial files.

Sonarr ownership, playable JP+EN destination and exact staged provenance are
independent prerequisites. qB torrents are removed only with strong DB+tag
ownership and complete selected-payload proof. Nothing deletes automatically.
"""
import hashlib
import json
import logging
import os
import sqlite3
import stat
import time
from collections import Counter
from pathlib import Path

from anime_audio_verification import confirmed_jp_en
from anime_qb_ownership import OWNED, ownership_for_series, owned_now, ownership
from anime_sonarr import _request
from anime_sonarr_import import plan_staged_imports
from anime_sonarr_reconciliation import check_series

LOG=logging.getLogger("anime_discovery.sonarr.duplicate_cleanup")
VIDEO={".mkv",".mp4",".m4v",".avi"}

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS sonarr_duplicate_cleanup_audit (
        id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id),
        recorded_at INTEGER NOT NULL, approved_by TEXT NOT NULL,
        result TEXT NOT NULL, item_json TEXT NOT NULL, reason TEXT NOT NULL)""")

def _sha(path):
    digest=hashlib.sha256()
    with open(path,"rb") as stream:
        for part in iter(lambda:stream.read(1024*1024),b""):
            digest.update(part)
    return digest.hexdigest()

def _trusted_file(path,root):
    """Verify each existing path component, not just its resolved final target."""
    base=Path(root).resolve(strict=True)
    candidate=Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts or candidate==base:
        raise ValueError("Unsafe staged path")
    if not candidate.is_relative_to(base):
        raise ValueError("Staged path outside trial root")
    rel=candidate.relative_to(base)
    current=base
    for part in rel.parts:
        current=current/part
        if current.is_symlink():
            raise ValueError("Symlink in staged path")
    if not candidate.is_file():
        raise ValueError("Staged file missing")
    meta=candidate.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1:
        raise ValueError("Unsafe hardlinked or nonregular staging file")
    return meta

def _sonarr_destination_map(settings,secrets,sonarr_id,*,opener=None):
    kwargs={} if opener is None else {"opener":opener}
    cfg=settings["sonarr"]
    rows=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET",
                  "episodefile?seriesId="+str(sonarr_id),**kwargs)
    if not isinstance(rows,list):raise RuntimeError("Sonarr file inventory invalid")
    ids={}
    for row in rows:
        if not isinstance(row,dict):raise RuntimeError("Malformed Sonarr file inventory")
        fid=row.get("id")
        if type(fid) is int and fid>0:
            if fid in ids:raise RuntimeError("Ambiguous Sonarr file identity")
            ids[fid]=row
    return ids

def review(db,series_id,settings,secrets,*,opener=None,audio_probe=confirmed_jp_en):
    """Fresh review; NEVER infer file equivalence from hasFile or filename."""
    if db.in_transaction:raise ValueError("Autocommit database required")
    if type(series_id) is not int or series_id<=0:raise ValueError("Invalid series ID")
    snapshot=check_series(db,series_id,settings,secrets,opener=opener)
    plan=plan_staged_imports(db,series_id,trial_root=settings["storage"]["trial_root"])
    if len(plan)>100:raise ValueError("Review too large")
    by_key={(e["season"],e["episode"]):e for e in snapshot["episodes"]}
    ids=(_sonarr_destination_map(settings,secrets,snapshot["sonarr_id"],opener=opener)
         if snapshot["sonarr_id"] else {})
    roots=settings["sonarr"]["root_folder"]
    review_items=[]
    for item in plan:
        number=(item["season"],item["episode"])
        state=by_key.get(number)
        status=state["status"] if state else "NEEDS_REVIEW"
        reason=""
        metadata=None
        if status=="REGISTERED":
            record=ids.get(state["sonarr_episode_file_id"])
            path=record.get("path") if record else None
            try:
                if (not isinstance(path,str) or not Path(path).is_absolute()
                        or not Path(path).resolve(strict=True).is_relative_to(Path(roots).resolve(strict=True))
                        or Path(path).resolve(strict=True).is_relative_to(Path(settings["storage"]["trial_root"]).resolve(strict=True))):
                    raise ValueError("Destination path untrusted")
                dest=Path(path)
                if dest.is_symlink() or not dest.is_file() or dest.stat().st_size<=0:
                    raise ValueError("Destination unavailable")
                if not audio_probe(str(dest)):
                    raise ValueError("Sonarr file lacks confirmed separate JP and EN tracks")
                src=item["path"]
                metadata=_trusted_file(src,settings["storage"]["trial_root"])
                if Path(src).resolve()==dest.resolve():
                    raise ValueError("Sonarr library is the staged source")
                if not metadata.st_size:raise ValueError("Empty staged source")
            except (OSError,ValueError,RuntimeError) as exc:
                status="NEEDS_REVIEW"
                reason=type(exc).__name__ if not isinstance(exc,ValueError) else str(exc)[:90]
        review_items.append({"notification_id":item["notification_id"],
            "season":item["season"],"episode":item["episode"],"path":item["path"],
            "size":metadata.st_size if metadata else None,
            "status":status,"reason":reason,
            "episode_file_id":state.get("sonarr_episode_file_id") if state else None})
    preserved=ownership_for_series(db,series_id)
    return {"series_id":series_id,"sonarr_id":snapshot["sonarr_id"],
            "monitored":snapshot["monitored"],"checked_at":snapshot["checked_at"],
            "episodes":review_items,"torrents":preserved,
            "eligible":sum(x["status"]=="REGISTERED" for x in review_items),
            "bytes_eligible":sum(x["size"] or 0 for x in review_items),
            "cleanup_authorized":False}

def _preflight_torrents(db,series_id,eligible,settings,qb):
    """Never delete a torrent containing any other selected or shared payload."""
    selected_ids={e["notification_id"] for e in eligible}
    expected={}
    for nid,h,digest in db.execute("""SELECT notification_id,lower(infohash),sha256
        FROM torrent_recovery_records WHERE notification_id IN ("""
        +",".join("?" for _ in selected_ids)+")",tuple(selected_ids)):
        if not isinstance(digest,str) or len(digest)!=64:
            continue
        if any(c not in "0123456789abcdef" for c in digest.lower()):continue
        expected.setdefault(h,{})[nid]=digest.lower()
    owned=[]
    preserved=[]
    for row in ownership_for_series(db,series_id):
        h=row["infohash"]
        if row["ownership"]!=OWNED:
            preserved.append(row)
            continue
        refs={nid for (nid,) in db.execute(
            "SELECT notification_id FROM torrent_recovery_records WHERE lower(infohash)=?",(h,))}
        if not refs or not refs<=selected_ids or not refs<=set(expected.get(h,{})):
            preserved.append({"infohash":h,"ownership":"SHARED_OR_INCOMPLETE"})
            continue
        # Provenance is checked again immediately before the destructive qB operation.
        if ownership(db,h)!=OWNED or not owned_now(db,h,qb):
            preserved.append({"infohash":h,"ownership":"UNCERTAIN"})
            continue
        torrent=qb.torrent_details(h)
        if torrent is None:
            continue
        save=Path(torrent["save_path"]).resolve(strict=True)
        root=Path(settings["storage"]["download_root"]).resolve(strict=True)
        trial=Path(settings["storage"]["trial_root"]).resolve(strict=True)
        library=Path(settings["sonarr"]["root_folder"]).resolve(strict=True)
        if not save.is_relative_to(root) or save.is_relative_to(trial) or save.is_relative_to(library):
            raise RuntimeError("Torrent save path outside isolated download root")
        media=[]
        for entry in qb.torrent_files(h):
            relative=Path(entry["name"])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Unsafe qB media name")
            if relative.suffix.lower() not in VIDEO:continue
            if type(entry.get("priority")) is not int or entry["priority"]<0:
                raise RuntimeError("Unverified qB file priority")
            if entry["priority"]==0:continue
            if entry.get("progress")!=1:
                raise RuntimeError("Active or incomplete qB file")
            origin=save/relative
            if not origin.is_file() or origin.is_symlink() or not origin.resolve().is_relative_to(root):
                raise RuntimeError("Unsafe qB media path")
            media.append(_sha(origin))
        if Counter(media)!=Counter(expected[h].values()):
            preserved.append({"infohash":h,"ownership":"PAYLOAD_UNVERIFIED"})
            continue
        owned.append(h)
    return owned,preserved

def _unlink_verified(path,root,expected):
    """Unlink only one exact regular file beneath a non-symlink trial directory."""
    previous=_trusted_file(path,root)
    if previous.st_dev!=expected.st_dev or previous.st_ino!=expected.st_ino or previous.st_size!=expected.st_size:
        raise RuntimeError("Staged file changed")
    parent=Path(path).parent
    fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_ino!=parent.stat().st_ino:
            raise RuntimeError("Staged parent changed")
        at=os.stat(Path(path).name,dir_fd=fd,follow_symlinks=False)
        if at.st_ino!=expected.st_ino or at.st_dev!=expected.st_dev or at.st_nlink!=1:
            raise RuntimeError("Staged file replaced")
        os.unlink(Path(path).name,dir_fd=fd)
    finally:
        os.close(fd)

def confirm(db,series_id,settings,secrets,*,approved=False,qb=None,opener=None,
            audio_probe=confirmed_jp_en):
    """Explicit operator approval, independent fresh proof, durable audit."""
    if approved is not True:raise PermissionError("Explicit cleanup confirmation required")
    if db.in_transaction:raise ValueError("Autocommit connection required")
    if qb is None:raise ValueError("Authenticated qB client required")
    ensure_schema(db)
    review_data=review(db,series_id,settings,secrets,opener=opener,audio_probe=audio_probe)
    db.execute("BEGIN IMMEDIATE")
    try:
        eligible=[x for x in review_data["episodes"] if x["status"]=="REGISTERED"]
        if not eligible:raise ValueError("No verified redundant trial episodes")
        # Prevent deleting files whose acquisition/dispatch may still be active.
        for item in eligible:
            row=db.execute("""SELECT d.state,COALESCE(j.state,'')
                FROM episode_dispatch d LEFT JOIN daemon_jobs j
                  ON j.kind='claimed_acquisition'
                 AND j.subject_key=CAST(d.notification_id AS TEXT)
                WHERE d.notification_id=?""",(item["notification_id"],)).fetchone()
            if not row or row[0]!="DONE" or row[1] in ("READY","DEFERRED","RUNNING","CLAIMED"):
                raise RuntimeError("Acquisition still active")
        # Never compete with the existing Keep import/finalization worker.
        status=db.execute("SELECT status FROM series WHERE id=?",(series_id,)).fetchone()[0]
        if status=="SONARR_IMPORT_PENDING":
            raise RuntimeError("Sonarr manual-copy import still pending")
        owned,preserved=_preflight_torrents(db,series_id,eligible,settings,qb)
        verified=[(e,_trusted_file(e["path"],settings["storage"]["trial_root"])) for e in eligible]
        now=int(time.time())
        audit={"episodes":[{"notification_id":e["notification_id"],
                            "path_sha256":hashlib.sha256(e["path"].encode()).hexdigest(),
                            "size":e["size"]} for e in eligible],
               "owned_torrents":owned,"preserved_torrents":preserved}
        cursor=db.execute("""INSERT INTO sonarr_duplicate_cleanup_audit
            (series_id,recorded_at,approved_by,result,item_json,reason)
            VALUES (?,?,?,'AUTHORIZED',?,'')""",
            (series_id,now,"authenticated_dashboard",json.dumps(audit,sort_keys=True)))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    audit_id=cursor.lastrowid
    removed=[]
    torrent_removed=[]
    errors=[]
    # Irreversible operations are outside the SQLite lock, audited individually.
    for h in owned:
        try:
            if not owned_now(db,h,qb):
                raise RuntimeError("Ownership no longer verified")
            qb.remove_torrent(h,delete_files=True)
            torrent_removed.append(h)
        except Exception as exc:
            errors.append("Torrent "+h[:12]+": "+type(exc).__name__)
    for entry,metadata in verified:
        try:
            # Fresh Sonarr/audio check again before unlink (not just old UI state).
            fresh=review(db,series_id,settings,secrets,opener=opener,audio_probe=audio_probe)
            matching=[e for e in fresh["episodes"]
                      if e["notification_id"]==entry["notification_id"]
                      and e["status"]=="REGISTERED"]
            if len(matching)!=1:raise RuntimeError("Stale Sonarr proof")
            _unlink_verified(entry["path"],settings["storage"]["trial_root"],metadata)
            removed.append(entry["notification_id"])
        except Exception as exc:
            errors.append("Trial episode "+str(entry["notification_id"])+": "+type(exc).__name__)
    outcome={"removed_notification_ids":removed,"removed_owned_torrents":torrent_removed,
             "preserved_torrents":preserved,"errors":errors}
    db.execute("""UPDATE sonarr_duplicate_cleanup_audit SET result=?,item_json=?,reason=?
        WHERE id=?""",("PARTIAL" if errors else "COMPLETED",
                       json.dumps({**audit,**outcome},sort_keys=True),
                       "SAFE_HOLD" if errors else "",audit_id))
    LOG.warning("event=SONARR_DUPLICATE_CLEANUP series_id=%d audit_id=%d trial_removed=%d owned_removed=%d preserved=%d errors=%d",
                series_id,audit_id,len(removed),len(torrent_removed),len(preserved),len(errors))
    return {"audit_id":audit_id,**outcome}
