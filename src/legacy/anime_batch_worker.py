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
