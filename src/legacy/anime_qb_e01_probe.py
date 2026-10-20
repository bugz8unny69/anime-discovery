"""Start ONLY an E01 probe from a verified, stopped qBittorrent manifest.

Composable batch-worker building block. Not connected to the production
single-episode worker. The caller must independently verify canonical
series identity and season *before* calling this function.

This module never unlocks E02-E06 or stages media. The later ffprobe gate
must supply durable evidence before doing either operation.
"""
import logging
from anime_batch_selection import (plan_gated_first_six,plan_verified_trial,
                                   plan_first_six,SelectionNeedsReview)
from anime_qb_manifest_intake import _validated_manifest, STOPPED
from anime_qb_ownership import OWNED, owned_now, ownership
from anime_trial_policy import window_for
from anime_trial_size_policy import (authorize_manifest_sizes, decide_trial_size,
                                     size_limits, TrialSizeRejected)

LOG=logging.getLogger("anime_discovery.trial")

def _inventory(files):
    """Immutable torrent file identity; priorities/progress may change."""
    return [(idx, name, size)
            for idx, name, size, _priority in _validated_manifest(files)]


def start_e01_probe(db, infohash, qb, *, season, stopped_manifest,
                    verified_window=None, verified_episode_map=None,
                    size_settings=None):
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
    trial_episode=1
    try:
        if verified_window is None and verified_episode_map is None:
            plan=plan_gated_first_six(original_files,season=season)
            # Inspect every eligible file even though ONLY E01 is selected.
            full_plan=plan_first_six(original_files,season=season)
        else:
            # Never unlock an absolute/part/ongoing numbering mode just
            # because a caller supplies an offset or a filename.
            if not isinstance(verified_window,dict) or not verified_window.get("evidence_ref"):
                raise ValueError("Durable provider-confirmed window required")
            stored=window_for(db,tvdb_id=verified_window.get("tvdb_id"),
                              anidb_id=verified_window.get("anidb_id"),
                              season=season)
            if stored!=verified_window or not stored.get("evidence_ref"):
                raise PermissionError("Trial window evidence not durably verified")
            trial_episode=stored["start"]
            plan=plan_verified_trial(original_files,season=season,
                                     start_episode=trial_episode,
                                     episode_map=verified_episode_map)
            # A pure dry planning phase, not ffprobe approval or actual unlock.
            full_plan=plan_verified_trial(original_files,season=season,
                                          start_episode=trial_episode,
                                          episode_map=verified_episode_map,
                                          probe_verified=True)
        if len(plan["wanted_indices"])!=1:
            raise SelectionNeedsReview("Cannot safely select unique first trial episode")
        idx=plan["wanted_indices"][0]
        if plan["wanted_episodes"]!={trial_episode:idx}:
            raise SelectionNeedsReview("First trial episode mapping is ambiguous")
    except (SelectionNeedsReview,ValueError,PermissionError) as exc:
        LOG.warning("event=TORRENT_SELECTION_REJECTED reason=%s hash=%s season=%d",
                    type(exc).__name__,infohash[:12],season)
        raise
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

    # qB supplied exact per-file byte sizes AFTER a stable stopped manifest.
    # Count only canonical trial episodes, not the full torrent or unrelated
    # seasons/attachments. All six known => combined limit overrides the
    # individual cap. Partial pack => individual AND running total caps.
    size_by_index = {idx: size for idx, _name, size in original}
    eligible_files = {
        ep: {"index": ix, "size": size_by_index[ix]}
        for ep, ix in full_plan["wanted_episodes"].items()
    }
    limits = size_limits(size_settings)
    if verified_window is not None:
        authorize_manifest_sizes(db, window=verified_window, infohash=infohash,
                                 episode_files=eligible_files, limits=limits)
    else:
        # Legacy callers do not supply durable series identity, so a per-pack
        # safety check is possible but no cross-release reservation can be made.
        try:
            verdict = decide_trial_size(
                {ep: row["size"] for ep, row in eligible_files.items()},
                start_episode=trial_episode, limits=limits)
        except TrialSizeRejected as exc:
            LOG.warning("event=TRIAL_SIZE_DECISION action=NEEDS_REVIEW reason=%s "
                        "season=%d episode=%s individual_limit_mb=%d "
                        "trial_limit_mb=%d torrent=%s",
                        exc.reason, season,
                        exc.episode if exc.episode is not None else "-",
                        limits["max_episode_mb"], limits["max_six_episode_mb"],
                        infohash[:12])
            raise
        LOG.info("event=TRIAL_SIZE_DECISION action=ELIGIBLE reason=%s "
                 "season=%d known_total_bytes=%d known_count=%d "
                 "individual_limit_mb=%d trial_limit_mb=%d torrent=%s",
                 verdict["reason"], season, verdict["trial_total_bytes"],
                 verdict["known_episode_count"], limits["max_episode_mb"],
                 limits["max_six_episode_mb"], infohash[:12])

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
            LOG.info("event=TORRENT_SELECTED reason=ALREADY_RUNNING hash=%s season=%d episode=%d file_index=%d skipped=%d",
                     infohash[:12],season,trial_episode,idx,len(skipped))
            return {"state":"PROBE_DOWNLOADING", "infohash":infohash.lower(),
                    "season":season, "episode":trial_episode, "file_index":idx,
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
    LOG.info("event=TORRENT_SELECTED reason=FIRST_TRIAL_EPISODE hash=%s season=%d episode=%d file_index=%d skipped=%d",
             infohash[:12],season,trial_episode,idx,len(skipped))
    return {"state":"PROBE_DOWNLOADING", "infohash":infohash.lower(),
            "season":season, "episode":trial_episode, "file_index":idx,
            "already_running":False}
