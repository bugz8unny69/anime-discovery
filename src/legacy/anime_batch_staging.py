"""Stage one completed batch file after verified per-file dual-audio evidence.

Each episode is independent. Recover from a crash between atomic staging and
SQLite finalization by checking the exact verified digest at the expected
destination; never overwrite a different file or trust stale qB progress.
"""
import logging
from pathlib import Path

from anime_batch_completion import inspect_completed_episode, BatchNeedsReview
from anime_trial_staging import stage_verified, staged_destination

LOG = logging.getLogger("anime_discovery.trial")


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_staged (
        tvdb_id TEXT NOT NULL, anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL, unit_key TEXT NOT NULL,
        episode INTEGER NOT NULL, infohash TEXT NOT NULL,
        file_index INTEGER NOT NULL, sha256 TEXT NOT NULL,
        staged_path TEXT NOT NULL, PRIMARY KEY(tvdb_id,season,unit_key,episode)
    )""")


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
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""INSERT OR IGNORE INTO anime_batch_staged VALUES (?,?,?,?,?,?,?,?,?)""",
                   (window["tvdb_id"],window["anidb_id"],window["season"],
                    window["unit_key"],episode,*evidence))
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
