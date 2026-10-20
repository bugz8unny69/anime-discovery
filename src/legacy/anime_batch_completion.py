"""Proof-bound qBittorrent E01 completion, JP+EN gate, and E02-E06 unlock.

Deliberately no release search or release-name identity inference. A caller
holds a leased verified batch job, its original stopped manifest, the
provider-bound canonical map, and an immutable trial window. This module
never treats torrent-wide progress as a per-file completion claim.
"""
import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path

from anime_audio_verification import confirmed_jp_en
from anime_batch_selection import plan_first_six, plan_verified_trial
from anime_qb_manifest_intake import _validated_manifest, STOPPED, _stop_and_wait
from anime_qb_ownership import OWNED, ownership, owned_now
from anime_trial_policy import window_for
from anime_trial_size_policy import authorize_manifest_sizes, size_limits

LOG = logging.getLogger("anime_discovery.trial")
ACTIVE = frozenset(("downloading", "stalledDL", "queuedDL", "forcedDL",
                    "uploading", "stalledUP", "queuedUP", "forcedUP"))


class BatchNeedsReview(ValueError):
    """Permanent batch/file problem; worker should set NEEDS_REVIEW."""


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_audio_proofs (
        tvdb_id TEXT NOT NULL, anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL, unit_key TEXT NOT NULL,
        infohash TEXT NOT NULL, episode INTEGER NOT NULL,
        file_index INTEGER NOT NULL, relative_name TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
        verified_at INTEGER NOT NULL,
        PRIMARY KEY(tvdb_id, season, unit_key, episode)
    )""")


def _window(db, window):
    if not isinstance(window, dict) or not window.get("evidence_ref"):
        raise PermissionError("Persisted provider-confirmed batch window required")
    stored = window_for(db, tvdb_id=window.get("tvdb_id"),
                        anidb_id=window.get("anidb_id"),
                        season=window.get("season"),
                        unit_key=window.get("unit_key"))
    if stored != window:
        raise PermissionError("Batch window differs from durable identity evidence")
    return stored


def _mapped_plan(files, window, episode_map, *, verified):
    if not isinstance(episode_map, dict) or not episode_map:
        raise BatchNeedsReview("Missing verified episode map")
    return plan_verified_trial(files, season=window["season"],
                               start_episode=window["start"],
                               episode_map=episode_map,
                               probe_verified=verified)


def _manifest_match(qb, infohash, stopped_manifest):
    if (not isinstance(stopped_manifest, dict) or
            stopped_manifest.get("state") != "MANIFEST_READY" or
            stopped_manifest.get("infohash") != infohash.lower()):
        raise BatchNeedsReview("Exact paused manifest required")
    original = _validated_manifest(stopped_manifest.get("files"))
    current = qb.torrent_files(infohash)
    actual = _validated_manifest(current)
    if [(i, n, s) for i, n, s, _ in original] != [
            (i, n, s) for i, n, s, _ in actual]:
        raise BatchNeedsReview("Torrent manifest changed")
    return current


def _owned(db, qb, infohash):
    if ownership(db, infohash) != OWNED or not owned_now(db, infohash, qb):
        raise PermissionError("Owned torrent provenance no longer verified")


def _file_path(qb, infohash, row, download_root):
    """Require save path below download root; refuse symlinks in every component."""
    root = Path(download_root).resolve(strict=True)
    if not root.is_dir():
        raise BatchNeedsReview("Download root missing")
    details = qb.torrent_identity(infohash)
    save = details.get("save_path") if isinstance(details, dict) else None
    if not isinstance(save, str) or not Path(save).is_absolute():
        raise BatchNeedsReview("qBittorrent save path is not verified")
    save_path = Path(save)
    # resolve(strict=True) on the save directory alone could traverse a
    # symlink; do not allow symlinks even if their target remains under root.
    try:
        relative_save = save_path.relative_to(root)
    except ValueError:
        raise BatchNeedsReview("qBittorrent save path outside download root") from None
    path = root
    for piece in (*relative_save.parts, *Path(row["name"]).parts):
        if piece in (".", "..", "") or piece == "/":
            raise BatchNeedsReview("Unsafe media path component")
        path = path / piece
        if path.is_symlink():
            raise BatchNeedsReview("Symlink in qBittorrent media path")
    if not path.is_file() or path.suffix.lower() not in (
            ".mkv", ".mp4", ".m4v", ".avi"):
        raise BatchNeedsReview("Completed video file missing")
    real = path.resolve(strict=True)
    if not real.is_relative_to(root) or real.stat().st_size != row["size"]:
        raise BatchNeedsReview("Completed video size/path mismatch")
    return real


def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def inspect_completed_episode(db, infohash, qb, *, window, stopped_manifest,
                              episode_map, episode, download_root,
                              runner=confirmed_jp_en):
    """Return DEFERRED while downloading; record immutable proof on JP+EN success.

    Only the qB selected file with exact verified name/index/size qualifies.
    Digest and ffprobe must read the same unchanged complete on-disk source.
    """
    if db.in_transaction:
        raise ValueError("Autocommit SQLite required")
    infohash = infohash.lower()
    _owned(db, qb, infohash)
    window = _window(db, window)
    current = _manifest_match(qb, infohash, stopped_manifest)
    mapped = _mapped_plan(current, window, episode_map, verified=True)["wanted_episodes"]
    if type(episode) is not int or episode not in mapped:
        raise BatchNeedsReview("Episode not mapped inside verified trial window")
    idx = mapped[episode]
    row = next(x for x in current if x["index"] == idx)
    if type(row.get("progress")) not in (float, int) or row["progress"] < 1:
        LOG.info("event=BATCH_EPISODE_WAIT reason=FILE_INCOMPLETE hash=%s season=%d episode=%d",
                 infohash[:12], window["season"], episode)
        return {"state": "DEFERRED", "reason": "FILE_INCOMPLETE"}
    # A fully downloaded file is not necessarily a selected or approved one.
    if type(row.get("priority")) is not int or row["priority"] <= 0:
        raise BatchNeedsReview("Completed episode not selected in qBittorrent")
    source = _file_path(qb, infohash, row, download_root)
    before = source.stat()
    if not runner(source):
        LOG.warning("event=BATCH_AUDIO_REJECTED reason=JAPANESE_ENGLISH_REQUIRED hash=%s season=%d episode=%d",
                    infohash[:12], window["season"], episode)
        raise BatchNeedsReview("JAPANESE_ENGLISH_REQUIRED")
    digest = _digest(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise BatchNeedsReview("Source changed during audio verification")
    # Re-read qB file inventory + exact completion after probing.
    verified = _manifest_match(qb, infohash, stopped_manifest)
    matching = next(x for x in verified if x["index"] == idx)
    if matching.get("progress") != 1 or matching.get("priority", 0) <= 0:
        raise BatchNeedsReview("Torrent changed while verifying completed episode")
    proof = (window["tvdb_id"], window["anidb_id"], window["season"],
             window["unit_key"], infohash, episode, idx, row["name"],
             row["size"], digest)
    ensure_schema(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        previous = db.execute("""SELECT tvdb_id,anidb_id,season,unit_key,infohash,
                         episode,file_index,relative_name,size_bytes,sha256
                         FROM anime_batch_audio_proofs
                         WHERE tvdb_id=? AND season=? AND unit_key=? AND episode=?""",
                         (window["tvdb_id"], window["season"],
                          window["unit_key"], episode)).fetchone()
        if previous and previous != proof:
            raise BatchNeedsReview("Conflicting durable episode audio proof")
        if not previous:
            db.execute("""INSERT INTO anime_batch_audio_proofs VALUES
                (?,?,?,?,?,?,?,?,?,?,?)""", (*proof, int(time.time())))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    LOG.info("event=BATCH_AUDIO_VERIFIED reason=JP_EN_FFPROBE hash=%s season=%d episode=%d file_index=%d",
             infohash[:12], window["season"], episode, idx)
    return {"state": "VERIFIED", "source": source, "file_index": idx,
            "sha256": digest, "episode": episode}


def unlock_verified_remaining(db, infohash, qb, *, window, stopped_manifest,
                              episode_map, size_settings=None, sleep=time.sleep):
    """Stop, revalidate persisted E01 audio proof, select E01-E06, resume.

    Never accepts a caller-controlled probe_verified boolean. Proof must
    match the exact original torrent/index/name/bytes. No ffprobe shortcut.
    """
    if db.in_transaction:
        raise ValueError("Autocommit SQLite required")
    infohash = infohash.lower()
    _owned(db, qb, infohash)
    window = _window(db, window)
    current = _manifest_match(qb, infohash, stopped_manifest)
    probe = _mapped_plan(current, window, episode_map, verified=False)
    full = _mapped_plan(current, window, episode_map, verified=True)
    first = window["start"]
    if len(probe["wanted_indices"]) != 1:
        raise BatchNeedsReview("First episode mapping missing")
    idx = probe["wanted_indices"][0]
    row = next(x for x in current if x["index"] == idx)
    ensure_schema(db)
    saved = db.execute("""SELECT infohash,file_index,relative_name,size_bytes
        FROM anime_batch_audio_proofs
        WHERE tvdb_id=? AND anidb_id=? AND season=? AND unit_key=? AND episode=?""",
        (window["tvdb_id"], window["anidb_id"], window["season"],
         window["unit_key"], first)).fetchone()
    if saved != (infohash, idx, row["name"], row["size"]):
        raise BatchNeedsReview("No durable matching first-episode audio proof")
    # Prevent extra download on a partial / oversized batch, including
    # settings tightened after the initial E01 probe.
    by_index = {f["index"]: f["size"] for f in current}
    eligible = {ep: {"index": ix, "size": by_index[ix]}
                for ep, ix in full["wanted_episodes"].items()}
    authorize_manifest_sizes(db, window=window, infohash=infohash,
                             episode_files=eligible, limits=size_limits(size_settings))
    detail = qb.torrent_identity(infohash)
    expected = set(full["wanted_indices"])
    priorities = {f["index"]: f["priority"] for f in current}
    if detail["state"] in ACTIVE and all(
            priorities.get(i) == (1 if i in expected else 0) for i in priorities):
        return {"state": "UNLOCKED", "already_running": True}
    if detail["state"] not in STOPPED:
        _stop_and_wait(qb, infohash, sleep=sleep)
    _owned(db, qb, infohash)
    if [(i,n,s) for i,n,s,_ in _validated_manifest(qb.torrent_files(infohash))] != [
            (i,n,s) for i,n,s,_ in _validated_manifest(current)]:
        raise BatchNeedsReview("Manifest changed during unlock pause")
    wanted, skipped = full["wanted_indices"], full["skip_indices"]
    qb.apply_stopped_file_selection(infohash, wanted_indices=wanted,
                                    skip_indices=skipped)
    _owned(db, qb, infohash)
    qb.start_selected_torrent(infohash, wanted_indices=wanted,
                              skip_indices=skipped)
    LOG.info("event=BATCH_EPISODES_UNLOCKED reason=E01_FFPROBE_PROVED hash=%s season=%d first=%d selected=%d",
             infohash[:12], window["season"], first, len(wanted))
    return {"state": "UNLOCKED", "already_running": False,
            "wanted_episodes": sorted(full["wanted_episodes"])}
