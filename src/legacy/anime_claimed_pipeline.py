"""Explicitly invoked acquisition-to-staging workflow.

Not registered in the live daemon. Source removal and Shoko writes are absent.
The caller supplies a verified qBittorrent adapter and filesystem roots.
"""
from pathlib import Path
from anime_acquisition_gate import approved_dispatch
from anime_acquisition_flow import acquire_claimed
from anime_completed_snapshot import completed_torrent_snapshot
from anime_media_completion import verified_media
from anime_media_flow import stage_claimed
from anime_source_retention import retain_recovery_record
from anime_trial_staging import staged_destination

def process_claimed(db, notification_id, *, infohash, magnet_uri, qb,
                    download_root, trial_root, title, tvdb_id, english_title=None,
                    staged_owner="",staged_group="", staged_directory_mode="2770", staged_file_mode="0640", selected_file_index=None):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    approval=approved_dispatch(db,notification_id)
    if not isinstance(title,str) or not title.strip():
        raise ValueError("Missing series title")
    # Do not submit an external action until all local prerequisites exist.
    if not Path(download_root).is_dir() or not Path(trial_root).is_dir():
        raise ValueError("Media roots must exist")
    submitted=acquire_claimed(db,notification_id,infohash,magnet_uri,qb)
    if not submitted:
        return {"state":"DEFERRED","reason":"Torrent submission requires reconciliation"}
    try:
        torrent=completed_torrent_snapshot(qb,infohash)
    except ValueError as exc:
        if str(exc)=="Expected exactly one matching torrent":
            return {"state":"DEFERRED","reason":"Torrent not visible for verification"}
        raise
    if torrent.get("progress")!=1 or torrent.get("state") not in ("uploading","stalledUP","pausedUP","queuedUP","forcedUP"):
        return {"state":"DEFERRED","reason":"Torrent not in completed state"}
    source=verified_media(torrent,download_root)
    # Source-first checks are inside stage_claimed; no NFO failure deletes media.
    try:
        staged=stage_claimed(db,notification_id,torrent,download_root,trial_root,
                             title=title,tvdb_id=tvdb_id,english_title=english_title,
                             staged_owner=staged_owner,staged_group=staged_group,
            staged_directory_mode=staged_directory_mode,staged_file_mode=staged_file_mode)
    except FileExistsError:
        # A previous worker may have copied media before its lease expired.
        # Reconcile only the exact expected destination; never overwrite it.
        dest=staged_destination(trial_root,title=title,english_title=english_title,
            season=approval["season"],episode=approval["episode"],suffix=source.suffix)
        if dest.is_symlink() or not dest.is_file():
            return {"state":"NEEDS_REVIEW","reason":"Expected staged media missing or unsafe"}
        staged=dest
    record=retain_recovery_record(db,infohash=infohash,magnet_uri=magnet_uri,
                                  source=source,staged=staged,
                                  notification_id=notification_id)
    return {"state":"DONE","staged_path":str(staged),
            "sha256":record["sha256"],"series_id":approval["series_id"]}
