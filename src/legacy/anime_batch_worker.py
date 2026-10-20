"""Leased season-pack job: exact Autobrr magnet, verified mapping, gated staging.

Uses the independent identity-monitor authorization and no replacement search.
Only qB file indexes, completed file bytes and ffprobe remain post-intake.
"""
import asyncio
import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from anime_batch_verified_intake import JOB_KIND
from anime_batch_selection import _video_episode, plan_verified_trial, SelectionNeedsReview
from anime_batch_completion import BatchNeedsReview, unlock_verified_remaining
from anime_batch_staging import stage_completed_batch_file
from anime_qb_manifest_intake import submit_poll_pause
from anime_qb_e01_probe import start_e01_probe
from anime_trial_policy import window_for
from anime_trial_size_policy import size_limits
from anime_verified_episode_map import from_anime_lists
from anime_identity_mapping_v4 import mappings

LOG = logging.getLogger("anime_discovery.trial")


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_executions (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        state TEXT NOT NULL CHECK(state IN ('MANIFEST_READY','PROBE','UNLOCKED','DONE')),
        infohash TEXT NOT NULL, manifest_json TEXT NOT NULL,
        map_json TEXT NOT NULL
    )""")


def _episode_mapping(files, *, season, tvdb_id, anidb_id, xml_bytes):
    """Prefer source-bound Anime-Lists mapping; never infer from file order."""
    import re
    release_numbers=[]
    explicit_relative=True
    for file in files:
        parsed=_video_episode(file["name"],season)
        if parsed is None:
            continue
        release_numbers.append(parsed[1])
        base=Path(file["name"]).stem
        if not re.search(r"(?i)(?<![a-z0-9])S0*%d[ ._-]*E\d{1,4}(?!\d)"%season,base):
            explicit_relative=False
    if not release_numbers or len(release_numbers)!=len(set(release_numbers)):
        raise BatchNeedsReview("DUPLICATE_OR_UNMAPPED_EPISODE")
    try:
        mapped=from_anime_lists(xml_bytes,anidb_id=anidb_id,tvdb_id=tvdb_id,
                                season=season,release_episodes=release_numbers)["episode_map"]
        if 1 in mapped.values():
            return mapped
    except ValueError:
        pass
    # Explicit S02E01-style naming is direct canonical numbering. Only
    # accept when the independent provider record confirms this season.
    rows=mappings(xml_bytes,anidb_id)
    if (not explicit_relative or 1 not in release_numbers or len(rows)!=1
            or rows[0].get("tvdbid")!=str(tvdb_id)
            or rows[0].get("defaulttvdbseason")!=str(season)):
        raise BatchNeedsReview("PROVIDER_EPISODE_MAPPING_UNAVAILABLE")
    return {number:number for number in release_numbers}


def _store(db, notification_id, state, infohash, manifest, episode_map):
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    original=json.dumps(manifest,sort_keys=True)
    mapped=json.dumps(episode_map,sort_keys=True)
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("""SELECT infohash,manifest_json,map_json FROM anime_batch_executions
                          WHERE notification_id=?""",(notification_id,)).fetchone()
        if old and old!=(infohash,original,mapped):
            raise BatchNeedsReview("BATCH_PLAN_CHANGED_AFTER_RESERVATION")
        db.execute("""INSERT INTO anime_batch_executions VALUES (?,?,?,?,?)
            ON CONFLICT(notification_id) DO UPDATE SET state=excluded.state""",
            (notification_id,state,infohash,original,mapped))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def step(db, job, qb, *, download_root, trial_root, settings, runner=None):
    """Advance one safely leased job by a bounded action; no idle busy loop."""
    if db.in_transaction or not isinstance(job,dict) or job.get("kind")!=JOB_KIND:
        raise ValueError("Verified batch job with autocommit connection required")
    lease=db.execute("""SELECT 1 FROM daemon_jobs WHERE id=? AND kind=?
        AND state='LEASED' AND lease_token=? AND lease_until>strftime('%s','now')""",
        (job.get("id"),JOB_KIND,job.get("lease_token"))).fetchone()
    if not lease:
        raise PermissionError("Stale verified batch lease")
    payload=json.loads(job["payload_json"])
    if (not isinstance(payload,dict) or set(payload)!={"notification_id"}
            or type(payload["notification_id"]) is not int
            or str(payload["notification_id"])!=job.get("subject_key")):
        raise BatchNeedsReview("UNVERIFIED_BATCH_JOB_PAYLOAD")
    nid=payload["notification_id"]
    row=db.execute("""SELECT a.tvdb_id,a.anidb_id,a.season,a.unit_key,a.title,
        a.xml_sha256,a.infohash,p.magnet_uri,n.status
        FROM anime_batch_authorizations a
        JOIN anime_batch_pending p ON p.notification_id=a.notification_id
        JOIN notifications n ON n.id=a.notification_id
        WHERE a.notification_id=?""",(nid,)).fetchone()
    if not row or row[8]!="APPROVED_BATCH":
        raise BatchNeedsReview("BATCH_IDENTITY_NOT_AUTHORIZED")
    tvdb,anidb,season,unit,title,xml_sha,infohash,magnet,_=row
    window=window_for(db,tvdb_id=tvdb,anidb_id=anidb,season=season)
    if window["unit_key"]!=unit or not window.get("evidence_ref"):
        raise BatchNeedsReview("PERSISTED_BATCH_WINDOW_MISSING")
    limits=size_limits(settings["trial"])
    ensure_schema(db)
    record=db.execute("""SELECT state,infohash,manifest_json,map_json
        FROM anime_batch_executions WHERE notification_id=?""",(nid,)).fetchone()
    if record is None:
        # This is the sole torrent-submission stage. On a delayed metadata
        # response, submit_once reconciles by hash rather than adding again.
        acquired=submit_poll_pause(db,infohash,magnet,qb)
        if acquired["state"]=="DEFERRED":
            return "DEFERRED"
        if acquired["state"]!="MANIFEST_READY":
            raise BatchNeedsReview("BATCH_MANIFEST_INTAKE_REJECTED")
        xml_path=Path(settings["daemon"]["database_path"]).parent/"anime-lists.xml"
        try:
            xml=xml_path.read_bytes()
        except OSError:
            return "DEFERRED"
        if hashlib.sha256(xml).hexdigest()!=xml_sha:
            raise BatchNeedsReview("PROVIDER_CACHE_CHANGED")
        try:
            episode_map=_episode_mapping(acquired["files"],season=season,
                tvdb_id=tvdb,anidb_id=anidb,xml_bytes=xml)
            probe=plan_verified_trial(acquired["files"],season=season,
                start_episode=window["start"],episode_map=episode_map)
        except (ValueError, SelectionNeedsReview) as exc:
            raise BatchNeedsReview("BATCH_EPISODES_UNMAPPABLE") from exc
        if len(probe["wanted_indices"])!=1:
            raise BatchNeedsReview("FIRST_BATCH_EPISODE_MISSING")
        _store(db,nid,"MANIFEST_READY",infohash,acquired,episode_map)
        record=("MANIFEST_READY",infohash,json.dumps(acquired),json.dumps(episode_map))
    state,saved_hash,manifest_json,map_json=record
    if saved_hash!=infohash:
        raise BatchNeedsReview("AUTHORIZED_TORRENT_CHANGED")
    manifest=json.loads(manifest_json)
    episode_map={int(key):value for key,value in json.loads(map_json).items()}
    if state=="MANIFEST_READY":
        start_e01_probe(db,infohash,qb,season=season,stopped_manifest=manifest,
                        verified_window=window,verified_episode_map=episode_map,
                        size_settings=limits)
        _store(db,nid,"PROBE",infohash,manifest,episode_map)
        return "DEFERRED"
    if state=="PROBE":
        args=dict(window=window,stopped_manifest=manifest,episode_map=episode_map,
                  episode=window["start"],download_root=download_root,
                  trial_root=trial_root,title=title)
        if runner is not None:
            args["runner"]=runner
        first=stage_completed_batch_file(db,infohash,qb,**args)
        if first["state"]=="DEFERRED":
            return "DEFERRED"
        unlock_verified_remaining(db,infohash,qb,window=window,
            stopped_manifest=manifest,episode_map=episode_map,size_settings=limits)
        _store(db,nid,"UNLOCKED",infohash,manifest,episode_map)
        return "DEFERRED"
    if state=="UNLOCKED":
        eligible=plan_verified_trial(manifest["files"],season=season,
            start_episode=window["start"],episode_map=episode_map,
            probe_verified=True)["wanted_episodes"]
        complete=True
        for episode in sorted(eligible):
            args=dict(window=window,stopped_manifest=manifest,episode_map=episode_map,
                      episode=episode,download_root=download_root,
                      trial_root=trial_root,title=title)
            if runner is not None:
                args["runner"]=runner
            outcome=stage_completed_batch_file(db,infohash,qb,**args)
            complete=complete and outcome["state"]=="STAGED"
        if not complete:
            return "DEFERRED"
        _store(db,nid,"DONE",infohash,manifest,episode_map)
        LOG.info("event=BATCH_TRIAL_COMPLETED reason=ALL_PRESENT_EPISODES_STAGED "
                 "tvdb=%s season=%d hash=%s",tvdb,season,infohash[:12])
        return "DONE"
    if state=="DONE":
        return "DONE"
    raise BatchNeedsReview("UNEXPECTED_BATCH_EXECUTION_STATE")


def handler_factory(db_path, qb_factory, *, download_root, trial_root,
                    settings_supplier, runner=None):
    """Create one async job handler; qB credentials are loaded per job."""
    async def handler(job):
        def execute():
            with sqlite3.connect(db_path,isolation_level=None,timeout=10) as db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA busy_timeout=10000")
                kwargs=dict(download_root=download_root,trial_root=trial_root,
                            settings=settings_supplier(job))
                if runner is not None:
                    kwargs["runner"]=runner
                return step(db,job,qb_factory(job),**kwargs)
        return await asyncio.to_thread(execute)
    return handler
