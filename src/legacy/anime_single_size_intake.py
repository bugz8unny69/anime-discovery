"""Size-first qB admission for approved single-episode Autobrr/Prowlarr jobs.

No release search. E01 gate for later single episodes checks durable prior
dual-audio staging before even submitting a torrent. With manifest available,
only a uniquely mapped target video is allowed by the hard trial-size ledger.
"""
import json
import logging

from anime_acquisition_gate import approved_dispatch
from anime_batch_completion import BatchNeedsReview, ACTIVE
from anime_batch_selection import _video_episode, VIDEO_SUFFIXES
from anime_qb_manifest_intake import submit_poll_pause, _validated_manifest, STOPPED
from anime_qb_ownership import OWNED, ownership, owned_now
from anime_trial_policy import window_for
from anime_trial_size_policy import authorize_manifest_sizes, size_limits

LOG=logging.getLogger("anime_discovery.trial")


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_single_file_admissions (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        infohash TEXT NOT NULL, file_index INTEGER NOT NULL,
        name TEXT NOT NULL, size_bytes INTEGER NOT NULL
    )""")


def _first_staged(db, series_id, window):
    first=window["start"]
    record=db.execute("""SELECT 1 FROM episode_dispatch d
        JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
        WHERE d.series_id=? AND d.season=? AND d.episode=?
          AND d.state='DONE' AND length(r.sha256)=64 LIMIT 1""",
        (series_id,window["season"],first)).fetchone()
    if record:
        return True
    # A verified batch E01 may have been staged outside the older single
    # episode recovery table.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_batch_staged'").fetchone():
        record=db.execute("""SELECT 1 FROM anime_batch_staged s
            JOIN anime_batch_audio_proofs p
            ON p.tvdb_id=s.tvdb_id AND p.season=s.season
             AND p.unit_key=s.unit_key AND p.episode=s.episode
             AND p.sha256=s.sha256
            WHERE s.tvdb_id=? AND s.anidb_id=? AND s.season=?
              AND s.unit_key=? AND s.episode=? LIMIT 1""",
            (window["tvdb_id"],window["anidb_id"],window["season"],
             window["unit_key"],first)).fetchone()
    return bool(record)


def admit_single_episode(db, notification_id, infohash, magnet_uri, qb, *,
                         size_settings=None):
    """Return selected index only when owned, mapped, sized and safely started.

    DEFERRED is a normal wait (first-episode probe or metadata). Permanent
    failures raise Needs Review without issuing replacement release searches.
    """
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    approval=approved_dispatch(db,notification_id)
    series_id,season,episode=(approval[x] for x in ("series_id","season","episode"))
    bound=db.execute("SELECT tvdb_id,anidb_id FROM verified_series_identity WHERE notification_id=?",
                     (notification_id,)).fetchone()
    if not bound:
        raise BatchNeedsReview("MISSING_VERIFIED_SINGLE_IDENTITY")
    window=window_for(db,tvdb_id=bound[0],anidb_id=bound[1],season=season)
    if episode<window["start"] or episode>window["end"]:
        raise BatchNeedsReview("SINGLE_EPISODE_OUTSIDE_TRIAL")
    if episode>window["start"] and not _first_staged(db,series_id,window):
        LOG.info("event=SINGLE_EPISODE_WAIT reason=FIRST_EPISODE_NOT_YET_STAGED tvdb=%s season=%d episode=%d",
                 bound[0],season,episode)
        return {"state":"DEFERRED","reason":"FIRST_EPISODE_NOT_YET_STAGED"}
    limits=size_limits(size_settings)
    ensure_schema(db)
    previous=db.execute("""SELECT infohash,file_index,name,size_bytes
        FROM anime_single_file_admissions WHERE notification_id=?""",
        (notification_id,)).fetchone()
    if previous is None:
        intake=submit_poll_pause(db,infohash,magnet_uri,qb)
        if intake["state"]=="DEFERRED":
            return {"state":"DEFERRED","reason":intake.get("reason")}
        if intake["state"]!="MANIFEST_READY":
            raise BatchNeedsReview("SINGLE_TORRENT_INTAKE_REJECTED")
        files=intake["files"]
        rows=_validated_manifest(files)
        video=[(idx,name,size) for idx,name,size,_ in rows
               if __import__("pathlib").PurePosixPath(name).suffix.lower() in VIDEO_SUFFIXES]
        if len(video)!=1:
            raise BatchNeedsReview("SINGLE_TORRENT_CONTAINS_MULTIPLE_OR_NO_VIDEOS")
        idx,name,size=video[0]
        number=_video_episode(name,season)
        if number is None:
            raise BatchNeedsReview("SINGLE_EPISODE_NAME_UNMAPPABLE")
        if number[1]!=episode:
            # Independently verified AniDB-number -> TVDB episode location is
            # allowed, but never invent an absolute-number offset.
            verified=db.execute("""SELECT anidb_episode_number FROM verified_anidb_episode_ids
                WHERE notification_id=? AND anidb_id=?""",
                (notification_id,int(bound[1]))).fetchone() if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='verified_anidb_episode_ids'").fetchone() else None
            if not verified or verified[0]!=number[1]:
                raise BatchNeedsReview("SINGLE_EPISODE_NUMBER_CONFLICT")
        authorize_manifest_sizes(db,window=window,infohash=infohash,
            episode_files={episode:{"index":idx,"size":size}},limits=limits)
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""INSERT OR IGNORE INTO anime_single_file_admissions VALUES (?,?,?,?,?)""",
                       (notification_id,infohash.lower(),idx,name,size))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        previous=(infohash.lower(),idx,name,size)
    if previous[0]!=infohash.lower():
        raise BatchNeedsReview("SINGLE_APPROVED_TORRENT_CHANGED")
    if ownership(db,infohash)!=OWNED or not owned_now(db,infohash,qb):
        raise PermissionError("Single episode ownership lost")
    current=qb.torrent_files(infohash)
    rows=_validated_manifest(current)
    expected=previous[1:]
    actual=[row for row in rows if row[0]==previous[1]]
    if len(actual)!=1 or actual[0][:3]!=expected:
        raise BatchNeedsReview("SINGLE_TORRENT_FILE_CHANGED")
    wanted=[previous[1]]
    skipped=[i for i,_,_,_ in rows if i not in wanted]
    priority={i:p for i,_,_,p in rows}
    detail=qb.torrent_identity(infohash)
    if detail and detail.get("state") in ACTIVE:
        if all(priority[i]==(1 if i in wanted else 0) for i in priority):
            return {"state":"READY","file_index":wanted[0]}
        raise BatchNeedsReview("SINGLE_ACTIVE_PRIORITY_MISMATCH")
    if not detail or detail.get("state") not in STOPPED:
        raise BatchNeedsReview("SINGLE_TORRENT_NOT_SAFELY_STOPPED")
    qb.apply_stopped_file_selection(infohash,wanted_indices=wanted,
                                    skip_indices=skipped)
    if ownership(db,infohash)!=OWNED or not owned_now(db,infohash,qb):
        raise PermissionError("Single episode ownership changed before resume")
    qb.start_selected_torrent(infohash,wanted_indices=wanted,
                              skip_indices=skipped)
    LOG.info("event=SINGLE_EPISODE_SELECTED reason=SIZE_AND_IDENTITY_VERIFIED "
             "tvdb=%s season=%d episode=%d size_bytes=%d hash=%s",
             bound[0],season,episode,previous[3],infohash[:12])
    return {"state":"READY","file_index":wanted[0]}
