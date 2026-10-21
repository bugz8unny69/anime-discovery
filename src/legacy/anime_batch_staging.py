"""Stage one completed batch file after verified per-file dual-audio evidence.

Each episode is independent. Recover from a crash between atomic staging and
SQLite finalization by checking the exact verified digest at the expected
destination; never overwrite a different file or trust stale qB progress.
"""
import hashlib
import json
import logging
import time
from pathlib import Path

from anime_batch_completion import inspect_completed_episode, BatchNeedsReview
from anime_trial_staging import stage_verified, staged_destination, reconcile_staged_metadata

LOG = logging.getLogger("anime_discovery.trial")


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_staged (
        tvdb_id TEXT NOT NULL, anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL, unit_key TEXT NOT NULL,
        episode INTEGER NOT NULL, infohash TEXT NOT NULL,
        file_index INTEGER NOT NULL, sha256 TEXT NOT NULL,
        staged_path TEXT NOT NULL, PRIMARY KEY(tvdb_id,season,unit_key,episode)
    )""")


def _publish_sonarr_record(db, *, series_id, window, episode,
                           infohash, sha256, staged_path, title):
    """Reuse the existing Sonarr Keep provenance contract for each batch file."""
    parent=db.execute("""SELECT a.notification_id,p.magnet_uri
        FROM anime_batch_authorizations a
        JOIN anime_batch_pending p ON p.notification_id=a.notification_id
        WHERE a.tvdb_id=? AND a.anidb_id=? AND a.season=? AND a.unit_key=?
          AND a.infohash=?""",
        (window["tvdb_id"],window["anidb_id"],window["season"],
         window["unit_key"],infohash.lower())).fetchone()
    if not parent:
        raise BatchNeedsReview("Batch Sonarr provenance not authorized")
    original_nid,magnet=parent
    guid="batch:%d:S%02dE%04d"%(original_nid,window["season"],episode)
    evidence=json.dumps({"tvdb_id":window["tvdb_id"],"anidb_id":window["anidb_id"],
        "season":window["season"],"episode":episode,"source":"verified_batch",
        "parent_notification_id":original_nid},sort_keys=True)
    previous=db.execute("""SELECT n.id,d.series_id,d.season,d.episode,d.state,
                                  r.infohash,r.sha256,r.staged_path
        FROM notifications n JOIN episode_dispatch d ON d.notification_id=n.id
        JOIN torrent_recovery_records r ON r.notification_id=n.id
        WHERE n.source='anime_batch' AND n.source_guid=?""",(guid,)).fetchone()
    wanted=(series_id,window["season"],episode,"DONE",infohash.lower(),sha256,str(staged_path))
    if previous:
        if previous[1:]!=wanted:
            raise BatchNeedsReview("Conflicting Sonarr batch episode provenance")
        return previous[0]
    # Never silently create a duplicate staged identity from another release.
    exists=db.execute("""SELECT 1 FROM episode_dispatch
        WHERE series_id=? AND season=? AND episode=? AND state='DONE'""",
        (series_id,window["season"],episode)).fetchone()
    if exists:
        raise BatchNeedsReview("Duplicate completed series/season episode")
    notification_id=db.execute("""INSERT INTO notifications
        (source,release_name,source_guid,info_hash,received_at,status)
        VALUES ('anime_batch',?,?,?,?, 'APPROVED')""",
        (("%s S%02dE%04d"%(title,window["season"],episode))[:200],
         guid,infohash.lower(),int(time.time()))).lastrowid
    db.execute("""INSERT INTO verified_series_identity
        (notification_id,anidb_id,tvdb_id,mapping_source,decision,
         episode_identity_verified,eligible_for_acquisition,evidence_json,evidence_sha256)
        VALUES (?,?,?,'verified_batch','VERIFIED',1,1,?,?)""",
        (notification_id,window["anidb_id"],window["tvdb_id"],
         evidence,hashlib.sha256(evidence.encode()).hexdigest()))
    db.execute("""INSERT INTO episode_verification_v16
        (notification_id,evaluated_at,decision,verified,evidence_json)
        VALUES (?,?,'VERIFIED',1,?)""",(notification_id,time.time(),evidence))
    db.execute("""INSERT INTO episode_approval_queue
        (notification_id,decision,season,episode)
        VALUES (?,'AUTO_APPROVED',?,?)""",
        (notification_id,window["season"],episode))
    db.execute("""INSERT INTO episode_dispatch
        (notification_id,series_id,season,episode,state,updated_at)
        VALUES (?,?,?,?,'DONE',?)""",
        (notification_id,series_id,window["season"],episode,int(time.time())))
    db.execute("""INSERT INTO torrent_recovery_records
        (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
        VALUES (?,?,?,?,?,?)""",
        (notification_id,infohash.lower(),magnet,str(staged_path),
         sha256,int(time.time())))
    return notification_id


def stage_completed_batch_file(db, infohash, qb, *, window, stopped_manifest,
                               episode_map, episode, download_root, trial_root,
                               title, runner=None, **permissions):
    """Probe and stage independently; NEVER accept torrent-wide completion."""
    if db.in_transaction:
        raise ValueError("Autocommit SQLite required")
    row = db.execute("SELECT id,status FROM series WHERE source='tvdb' AND external_id=?",
                     (window["tvdb_id"],)).fetchone()
    if not row or row[1] == "REJECTED" or db.execute(
            "SELECT 1 FROM series_rejection_blocks WHERE series_id=?",(row[0],)).fetchone() or db.execute(
            "SELECT 1 FROM series_quarantine WHERE series_id=?",(row[0],)).fetchone():
        raise BatchNeedsReview("Verified TVDB series missing, rejected or quarantined")
    args = {"window":window,"stopped_manifest":stopped_manifest,
            "episode_map":episode_map,"episode":episode,"download_root":download_root}
    if runner is not None:
        args["runner"] = runner
    status = inspect_completed_episode(db,infohash,qb,**args)
    if status["state"] == "DEFERRED":
        return status
    source = status["source"]
    expected = staged_destination(trial_root,title=title,season=window["season"],
                                  episode=episode,suffix=source.suffix)
    ensure_schema(db)
    previous = db.execute("""SELECT infohash,file_index,sha256,staged_path
        FROM anime_batch_staged WHERE tvdb_id=? AND season=? AND unit_key=? AND episode=?""",
        (window["tvdb_id"],window["season"],window["unit_key"],episode)).fetchone()
    evidence = (infohash.lower(),status["file_index"],status["sha256"],str(expected))
    if previous and previous != evidence:
        raise BatchNeedsReview("Conflicting completed batch staging evidence")
    if previous or expected.exists() or expected.is_symlink():
        # Recovery of an interrupted stage is allowed ONLY if the source
        # and existing destination have the independently verified digest.
        from anime_batch_completion import _digest
        if expected.is_symlink() or not expected.is_file() or _digest(expected)!=status["sha256"]:
            raise BatchNeedsReview("Existing staged episode differs from verified file")
    else:
        stage_verified(source,trial_root,title=title,tvdb_id=window["tvdb_id"],
                       season=window["season"],episode=episode,series_id=row[0],
                       **permissions)
    # A crash after publishing the verified video can leave NFO metadata
    # absent while the SQLite checkpoint is missing. Repair NFOs first,
    # then commit the staging checkpoint without recopying verified bytes.
    reconcile_staged_metadata(expected,title=title,tvdb_id=window["tvdb_id"],
        season=window["season"],episode=episode,
        staged_owner=permissions.get("staged_owner",""),
        staged_group=permissions.get("staged_group",""),
        staged_file_mode=permissions.get("staged_file_mode","0640"))
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""INSERT OR IGNORE INTO anime_batch_staged VALUES (?,?,?,?,?,?,?,?,?)""",
                   (window["tvdb_id"],window["anidb_id"],window["season"],
                    window["unit_key"],episode,*evidence))
        _publish_sonarr_record(db,series_id=row[0],window=window,episode=episode,
                               infohash=infohash,sha256=status["sha256"],
                               staged_path=expected,title=title)
        db.execute("""INSERT OR IGNORE INTO episodes(series_id,season,episode,status)
                      VALUES (?,?,?,'STAGED')""",(row[0],window["season"],episode))
        db.execute("""UPDATE episodes SET status='STAGED'
                      WHERE series_id=? AND season=? AND episode=?""",
                   (row[0],window["season"],episode))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    LOG.info("event=BATCH_EPISODE_STAGED reason=JP_EN_AND_SHA256_VERIFIED "
             "tvdb=%s season=%d episode=%d torrent=%s",
             window["tvdb_id"],window["season"],episode,infohash[:12])
    return {"state":"STAGED","episode":episode,"staged_path":str(expected)}
