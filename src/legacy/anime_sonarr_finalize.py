"""Finalize Sonarr Keep only after copied media and qB source safety checks.

All external operations are explicit; no deletion before full preflight.
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from anime_sonarr import _request

def _digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def _inside(path, root, *, allow_missing=False):
    resolved=Path(path).resolve(strict=not allow_missing)
    base=Path(root).resolve(strict=True)
    return resolved.is_relative_to(base) and resolved!=base

def confirm_sonarr_copies(settings,secrets,*,sonarr_id,plan,expected_digests,opener=None):
    """Require each Sonarr episode to point to an independent identical file."""
    cfg=settings["sonarr"]
    options={} if opener is None else {"opener":opener}
    files=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET",
                   "episodefile?seriesId="+str(sonarr_id),**options)
    episodes=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET",
                      "episode?seriesId="+str(sonarr_id),**options)
    if not isinstance(files,list) or not isinstance(episodes,list):
        raise RuntimeError("Sonarr episode inventory invalid")
    mapping={}
    for ep in episodes:
        if type(ep.get("id")) is int and type(ep.get("episodeFileId")) is int:
            mapping.setdefault((ep.get("seasonNumber"),ep.get("episodeNumber")),set()).add(ep["episodeFileId"])
    file_map={f.get("id"):f.get("path") for f in files if type(f.get("id")) is int}
    destinations=[]
    used=set()
    for item in plan:
        source=Path(item["path"])
        if not _inside(source,settings["storage"]["trial_root"],allow_missing=True):
            raise RuntimeError("Trial source outside trusted root")
        ids=mapping.get((item["season"],item["episode"]),set())
        matches=[file_map[id] for id in ids if id in file_map]
        if len(matches)!=1 or not matches[0] or not _inside(matches[0],cfg["root_folder"]):
            raise RuntimeError("Expected Sonarr episode file not verified")
        dest=Path(matches[0]).resolve(strict=True)
        if dest in used or dest==source.resolve(strict=False):
            raise RuntimeError("Sonarr destination overlaps trial file")
        used.add(dest)
        if not dest.is_file():
            raise RuntimeError("Sonarr copy missing")
        destination_digest=_digest(dest)
        expected=expected_digests.get(item["notification_id"])
        if source.is_file():
            if source.stat().st_size!=dest.stat().st_size or _digest(source)!=destination_digest:
                raise RuntimeError("Sonarr copy differs from staged source")
        elif expected is None:
            raise RuntimeError("Missing original has no trusted recovery digest")
        if expected and destination_digest!=expected:
            raise RuntimeError("Staged integrity digest mismatch")
        destinations.append(str(dest))
    return destinations

def finalize_import(db,series_id,settings,secrets,*,qb,opener=None):
    """Delete old trial/torrent sources only after confirming every Sonarr copy."""
    row=db.execute("""SELECT s.status,k.sonarr_id,m.submitted_command_id,m.manifest_json
       FROM series s JOIN sonarr_keep k ON k.series_id=s.id
       JOIN sonarr_import_manifest m ON m.series_id=s.id WHERE s.id=?""",(series_id,)).fetchone()
    if not row or row[0]!="SONARR_IMPORT_PENDING" or type(row[2]) is not int:
        raise ValueError("No submitted import pending")
    sonarr_id,command_id,raw=row[1:]
    options={} if opener is None else {"opener":opener}
    command=_request(settings["sonarr"]["base_url"],secrets["sonarr_api_key"],
                     "GET","command/"+str(command_id),**options)
    if command.get("status")!="completed":
        return {"complete":False,"reason":"Sonarr command not completed"}
    plan=json.loads(raw)
    if not isinstance(plan,list) or not plan:
        raise ValueError("Empty import manifest")
    ids=[item["notification_id"] for item in plan]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate notification in import manifest")
    rows=db.execute("""SELECT notification_id,infohash,sha256 FROM torrent_recovery_records
        WHERE notification_id IN ("""+",".join("?" for _ in ids)+")",ids).fetchall()
    if len(rows)!=len(ids):
        raise RuntimeError("Missing torrent provenance")
    hashes={str(infohash).lower() for _,infohash,_ in rows}
    digests={nid:digest for nid,_,digest in rows
             if isinstance(digest,str) and len(digest)==64 and all(c in "0123456789abcdef" for c in digest.lower())}
    destinations=confirm_sonarr_copies(settings,secrets,sonarr_id=sonarr_id,
        plan=plan,expected_digests=digests,opener=opener)
    # Shoko is best-effort and must NEVER gate safe Sonarr source cleanup.
    # Persist its provenance after verified Sonarr import, retaining a retry
    # record even after the trial and torrent sources have been removed.
    if settings.get("shoko",{}).get("enabled") is True:
        try:
            from anime_shoko_handoff_state import enqueue_verified_copies
            enqueue_verified_copies(db,series_id,plan,destinations)
        except Exception:
            # Keep an operator-visible failure rather than deleting known-good
            # permanent Sonarr files or retaining duplicate media indefinitely.
            import logging
            logging.getLogger(__name__).exception(
                "Shoko handoff queue failed for series %d",series_id)
    # Never delete a torrent referenced by another series or an unimported release.
    for infohash in hashes:
        referenced=db.execute("""SELECT r.notification_id FROM torrent_recovery_records r
            WHERE lower(r.infohash)=?""",(infohash,)).fetchall()
        if any(nid not in ids for (nid,) in referenced):
            raise RuntimeError("Torrent is shared with work outside this import")
    download_root=settings["storage"]["download_root"]
    for infohash in hashes:
        record=qb.torrent_details(infohash)
        if record is None:
            continue  # Already cleaned after staging; idempotent.
        save_path=record["save_path"]
        if (not (Path(save_path).resolve(strict=True)==Path(download_root).resolve(strict=True) or _inside(save_path,download_root))
            or Path(save_path).resolve().is_relative_to(Path(settings["sonarr"]["root_folder"]).resolve())
            or Path(save_path).resolve().is_relative_to(Path(settings["storage"]["trial_root"]).resolve())):
            raise RuntimeError("Torrent files not isolated in download root")
    # Require exact media payload equivalence. A torrent may contain more
    # episodes than were staged, even if only one was approved.
    from collections import Counter
    supported={".mkv",".mp4",".m4v",".avi"}
    for infohash in hashes:
        record=qb.torrent_details(infohash)
        if record is None:
            continue
        originals=[]
        for entry in qb.torrent_files(infohash):
            relative=Path(entry["name"])
            if relative.is_absolute() or ".." in relative.parts or relative.name in ("",".",".."):
                raise RuntimeError("Unsafe qB file name")
            if relative.suffix.lower() not in supported:
                continue
            original=Path(record["save_path"])/relative
            if original.is_symlink() or not original.is_file() or not _inside(original,download_root):
                raise RuntimeError("qB source outside isolated download root")
            originals.append(_digest(original))
        expected=Counter(digests[nid] for nid,h,digest in rows
                         if str(h).lower()==infohash and nid in ids and nid in digests)
        if not originals or Counter(originals)!=expected:
            raise RuntimeError("Original torrent media payload not fully imported")
    # Reaching this point proves the imported copies and torrent payload.
    for infohash in hashes:
        if qb.torrent_details(infohash) is not None:
            qb.remove_torrent(infohash,delete_files=True)
    for item in plan:
        Path(item["path"]).unlink(missing_ok=True)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE series SET status='KEPT' WHERE id=?",(series_id,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"complete":True,"sonarr_id":sonarr_id,"imported_files":len(destinations),
            "source_files_removed":len(plan),"torrents_reconciled":len(hashes)}
