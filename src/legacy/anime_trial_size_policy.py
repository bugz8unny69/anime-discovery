"""Hard six-episode trial budgets from the stopped qBittorrent file manifest.

Never trusts a release name, guessed episode offset, torrent total size, or
supplied filesystem path. The caller has already mapped each real qB file to
a *canonical* episode using verified identity evidence. This module does no
torrent/network writes. All reservations use one SQLite IMMEDIATE transaction
so independently arriving episodes cannot each consume the same free budget.
"""
import logging
import re

from anime_trial_policy import window_for

LOG = logging.getLogger("anime_discovery.trial")
MB = 1_000_000  # Dashboard explicitly uses decimal megabytes.
DEFAULT_LIMITS = {"max_episode_mb": 600, "max_six_episode_mb": 3000}
_HASH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class TrialSizeRejected(ValueError):
    """Permanent size admission failure; caller must mark NEEDS_REVIEW."""

    def __init__(self, reason, *, episode=None):
        super().__init__(reason)
        self.reason = reason
        self.episode = episode


def size_limits(settings=None):
    """Return validated size-limit settings. Caller passes settings['trial']."""
    values = DEFAULT_LIMITS if settings is None else settings
    if not isinstance(values, dict) or set(values) != set(DEFAULT_LIMITS):
        raise ValueError("Invalid trial size setting keys")
    if any(type(values[key]) is not int or not 1 <= values[key] <= 100_000
           for key in DEFAULT_LIMITS):
        raise ValueError("Trial size limits must be positive integer MB")
    return dict(values)


def _sizes(sizes, first, *, allow_empty=False):
    if not isinstance(sizes, dict) or (not sizes and not allow_empty):
        raise ValueError("Canonical episode size map required")
    if type(first) is not int or not 1 <= first <= 9994:
        raise ValueError("Invalid canonical trial start")
    last = first + 5
    if (
            any(type(ep) is not int or not first <= ep <= last or
                type(size) is not int or size <= 0 for ep, size in sizes.items())):
        raise ValueError("Invalid canonical episode or qB file size")
    return sizes


def decide_trial_size(incoming, *, start_episode, recorded=None, limits=None):
    """Pure size calculation, safe for either a full pack or future arrivals.

    Exactly six KNOWN canonical sizes, whether from one torrent or previously
    reserved individual files, authorize the total-budget exception. Until
    then, *new* episodes must also satisfy the per-episode cap. Existing
    reservations are not rejected retroactively for being individually large.
    """
    cfg = size_limits(limits)
    incoming = _sizes(incoming, start_episode)
    recorded = _sizes(recorded if recorded is not None else {},
                      start_episode, allow_empty=True)
    for ep, count in incoming.items():
        if ep in recorded and recorded[ep] != count:
            raise TrialSizeRejected("CONFLICTING_EPISODE_SIZE", episode=ep)
    combined = {**recorded, **incoming}
    total = sum(combined.values())
    all_known = len(combined) == 6
    if total > cfg["max_six_episode_mb"] * MB:
        raise TrialSizeRejected("TRIAL_TOTAL_EXCEEDED")
    if not all_known:
        for ep, byte_count in sorted(incoming.items()):
            if ep not in recorded and byte_count > cfg["max_episode_mb"] * MB:
                raise TrialSizeRejected("EPISODE_SIZE_EXCEEDED", episode=ep)
    return {"eligible": True, "complete_six": all_known,
            "trial_total_bytes": total, "known_episode_count": len(combined),
            "limits": cfg,
            "reason": ("FULL_SIX_WITHIN_BUDGET" if all_known
                       else "PARTIAL_TRIAL_WITHIN_BUDGET")}


def _log(action, reason, *, window, ep, size, total, limits, infohash):
    LOG.log(logging.INFO if action == "ELIGIBLE" else logging.WARNING,
            "event=TRIAL_SIZE_DECISION action=%s reason=%s tvdb=%s season=%d "
            "episode=%s size_bytes=%s known_total_bytes=%s "
            "individual_limit_mb=%d trial_limit_mb=%d torrent=%s",
            action, reason, window["tvdb_id"], window["season"],
            ep if ep is not None else "-", size if size is not None else "-",
            total if total is not None else "-",
            limits["max_episode_mb"], limits["max_six_episode_mb"], infohash[:12])


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_trial_size_reservations (
        tvdb_id TEXT NOT NULL,
        anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL,
        unit_key TEXT NOT NULL,
        episode INTEGER NOT NULL,
        infohash TEXT NOT NULL,
        file_index INTEGER NOT NULL,
        size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
        PRIMARY KEY(tvdb_id, season, unit_key, episode)
    )""")


def authorize_manifest_sizes(db, *, window, infohash, episode_files, limits=None):
    """Durably reserve verified canonical episode file sizes before qB resume.

    episode_files: {canonical_episode: {'index': qB_index, 'size': qB_size}}.
    All six sizes may be reserved at once even while only the first episode
    receives qB priority 1. Later calls with identical file evidence are
    idempotent; a different release/size for a reserved episode must use an
    explicit operator recovery action, not silently overwrite the ledger.

    Raises TrialSizeRejected for hard limit / conflicting release. Callers
    should mark NEEDS_REVIEW and notify, without trying alternate releases.
    """
    cfg = size_limits(limits)
    if db.in_transaction:
        raise ValueError("Autocommit SQLite connection required")
    if not isinstance(infohash, str) or not _HASH.fullmatch(infohash.lower()):
        raise ValueError("Torrent hash must be an exact hex BTIH")
    infohash = infohash.lower()
    if not isinstance(window, dict):
        raise ValueError("Verified trial window required")
    expected = window_for(db, tvdb_id=window.get("tvdb_id"),
                          anidb_id=window.get("anidb_id"),
                          season=window.get("season"))
    if expected != window:
        raise PermissionError("Trial window does not match persisted identity")
    first = window["start"]
    if not isinstance(episode_files, dict) or not episode_files:
        raise ValueError("Verified episode-to-file mapping required")
    indices = []
    incoming = {}
    for ep, entry in episode_files.items():
        if not isinstance(entry, dict) or set(entry) != {"index", "size"}:
            raise ValueError("Exact qB file index/size required")
        idx, size = entry["index"], entry["size"]
        if type(idx) is not int or idx < 0:
            raise ValueError("Invalid qB file index")
        indices.append(idx)
        incoming[ep] = size
    if len(indices) != len(set(indices)):
        raise ValueError("Duplicate qB file index")
    _sizes(incoming, first)
    # SQLite CREATE TABLE inside a first-use transaction is rolled back along
    # with a refused admission. Establish the schema independently so blocked
    # attempts leave a usable ledger for diagnostics and future retries.
    ensure_schema(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        rows = db.execute("""SELECT episode,infohash,file_index,size_bytes,anidb_id
            FROM anime_trial_size_reservations
            WHERE tvdb_id=? AND season=? AND unit_key=?""",
            (window["tvdb_id"], window["season"], window["unit_key"])).fetchall()
        previous = {}
        for ep, old_hash, old_idx, old_size, old_anidb in rows:
            if old_anidb != window["anidb_id"]:
                raise TrialSizeRejected("CONFLICTING_SERIES_IDENTITY", episode=ep)
            previous[ep] = old_size
            if ep in incoming and (old_hash, old_idx, old_size) != (
                    infohash, episode_files[ep]["index"], incoming[ep]):
                raise TrialSizeRejected("CONFLICTING_EPISODE_RESERVATION", episode=ep)
        verdict = decide_trial_size(incoming, start_episode=first,
                                   recorded=previous, limits=cfg)
        for ep, entry in incoming.items():
            db.execute("""INSERT OR IGNORE INTO anime_trial_size_reservations
                (tvdb_id,anidb_id,season,unit_key,episode,infohash,file_index,size_bytes)
                VALUES (?,?,?,?,?,?,?,?)""",
                (window["tvdb_id"], window["anidb_id"], window["season"],
                 window["unit_key"], ep, infohash, episode_files[ep]["index"], entry))
        db.commit()
    except TrialSizeRejected as exc:
        db.rollback()
        total = sum(previous.values()) + sum(
            size for ep, size in incoming.items() if ep not in previous)
        ep = exc.episode
        _log("NEEDS_REVIEW", exc.reason, window=window, ep=ep,
             size=incoming.get(ep), total=total, limits=cfg, infohash=infohash)
        raise
    except BaseException:
        db.rollback()
        raise
    for ep, size in sorted(incoming.items()):
        reason = verdict["reason"]
        if ep in previous:
            reason = "ALREADY_RESERVED"
        elif (verdict["complete_six"] and
              size > cfg["max_episode_mb"] * MB):
            reason = "FULL_SIX_OVERRIDES_EPISODE_LIMIT"
        _log("ELIGIBLE", reason, window=window, ep=ep, size=size,
             total=verdict["trial_total_bytes"], limits=cfg, infohash=infohash)
    return verdict
