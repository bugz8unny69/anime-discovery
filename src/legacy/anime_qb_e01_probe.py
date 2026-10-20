"""Start ONLY an E01 probe from a verified, stopped qBittorrent manifest.

Composable batch-worker building block. Not connected to the production
single-episode worker. The caller must independently verify canonical
series identity and season *before* calling this function.

This module never unlocks E02-E06 or stages media. The later ffprobe gate
must supply durable evidence before doing either operation.
"""
from anime_batch_selection import plan_gated_first_six, SelectionNeedsReview
from anime_qb_manifest_intake import _validated_manifest, STOPPED
from anime_qb_ownership import OWNED, owned_now, ownership

def _inventory(files):
    """Immutable torrent file identity; priorities/progress may change."""
    return [(idx, name, size)
            for idx, name, size, _priority in _validated_manifest(files)]


def start_e01_probe(db, infohash, qb, *, season, stopped_manifest):
    """Revalidate ownership and file identity, set E01-only, then resume.

    stopped_manifest must come from a successful submit_poll_pause() result.
    This operation is safe to repeat while an E01-only download is active;
    it never infers a successful Japanese+English probe from qB progress.
    """
    if db.in_transaction:
        raise ValueError("Autocommit database connection required")
    if (ownership(db, infohash) != OWNED or
            not owned_now(db, infohash, qb)):
        raise PermissionError("Exact torrent ownership is not proven")
    if not isinstance(stopped_manifest, dict) or stopped_manifest.get("state") != "MANIFEST_READY":
        raise ValueError("Verified stopped-torrent manifest required")
    if stopped_manifest.get("infohash") != infohash.lower():
        raise ValueError("Manifest torrent hash mismatch")
    original_files = stopped_manifest.get("files")
    original = _inventory(original_files)
    plan = plan_gated_first_six(original_files, season=season)
    if plan["phase"] != "PROBE_E01" or len(plan["wanted_indices"]) != 1:
        raise SelectionNeedsReview("Cannot safely select unique E01")
    idx = plan["wanted_indices"][0]
    if plan["wanted_episodes"] != {1:idx}:
        raise SelectionNeedsReview("Expected E01-only plan")
    current = qb.torrent_identity(infohash)
    if not current:
        raise RuntimeError("qBittorrent torrent missing")
    current_files = qb.torrent_files(infohash)
    if _inventory(current_files) != original:
        raise RuntimeError("qBittorrent file inventory changed after metadata pause")
    # DB ownership is durable, category/tag still must match; do not trust
    # an unrelated pre-existing same-hash torrent.
    if (ownership(db, infohash) != OWNED or
            not owned_now(db, infohash, qb)):
        raise PermissionError("Torrent ownership changed during selection")
    wanted = plan["wanted_indices"]
    skipped = plan["skip_indices"]

    if current.get("state") not in STOPPED:
        # A repeat call after a prior start should not reset priorities.
        # Only recognized transfer/seeding states qualify: never treat
        # an error, checking or metadata state as a healthy E01 probe.
        if current.get("state") not in (
                "downloading", "stalledDL", "queuedDL", "forcedDL",
                "uploading", "stalledUP", "queuedUP", "forcedUP"):
            raise RuntimeError("Torrent is not in a recognized E01 transfer state")
        priorities = {row["index"]: row.get("priority") for row in current_files}
        if (len(priorities) == len(current_files)
                and all(priorities.get(i) == (1 if i == idx else 0)
                        for i in range(len(current_files)))):
            return {"state":"PROBE_DOWNLOADING", "infohash":infohash.lower(),
                    "season":season, "episode":1, "file_index":idx,
                    "already_running":True}
        raise RuntimeError("Active torrent has unapproved priorities; stop it before retry")

    qb.apply_stopped_file_selection(infohash, wanted_indices=wanted,
                                    skip_indices=skipped)
    # The first readback of priorities happens in the adapter. A second
    # identity check prevents a file-index race before a download is resumed.
    if _inventory(qb.torrent_files(infohash)) != original:
        raise RuntimeError("Torrent manifest changed after applying priorities")
    if (ownership(db, infohash) != OWNED or
            not owned_now(db, infohash, qb)):
        raise PermissionError("Torrent ownership changed before resume")
    qb.start_selected_torrent(infohash, wanted_indices=wanted,
                              skip_indices=skipped)
    return {"state":"PROBE_DOWNLOADING", "infohash":infohash.lower(),
            "season":season, "episode":1, "file_index":idx,
            "already_running":False}
