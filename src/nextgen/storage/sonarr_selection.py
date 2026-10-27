"""One immutable Sonarr torrent choice per recognized episode, no torrent sends.

Invoke only from an admitted worker completion transaction. This is a source
selection receipt, not an acquisition reservation or qBittorrent send permit.
"""
import time

from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, Release, SearchResult, _magnet_hash
from src.nextgen.acquisition.metadata import infohash
from src.nextgen.sonarr_episode import VerifiedEpisode


class SelectionConflict(ValueError):
    reason_code = 'SONARR_SELECTION_CONFLICT'
    def __init__(self):
        super().__init__('Sonarr candidate selection needs review.')


def select(db, *, plan_id, identity, result, release, policy):
    """Select once; duplicate identical attempts are idempotent.

    Refuses unverified catalog-only episodes and any existing active acquisition.
    No URL, passkey, or magnet URI is persisted.
    """
    if (not db.in_transaction or type(plan_id) is not int or plan_id <= 0
            or type(identity) is not VerifiedEpisode
            or type(result) is not SearchResult or type(release) is not Release
            or type(policy) is not DiscoveryPolicy
            or not any(candidate is release for candidate in result.candidates)
            or result.series_id <= 0 or result.episode_id <= 0
            or release.mapped_episode_ids != (result.episode_id,)
            or not policy.accepts(release)
            or not release.info_hash
            or _magnet_hash(release.magnet_url) != release.info_hash):
        raise SelectionConflict()
    try: digest = infohash(release.info_hash)
    except ValueError: raise SelectionConflict() from None
    plan = db.execute(
        "SELECT anidb_id,tvdb_series_id,tvdb_season,anchor_episode,"
        "backfill_count,following_count FROM trial_plans "
        "WHERE plan_id=? AND tvdb_order='official'", (plan_id,)
    ).fetchone()
    if plan is None or plan[1:3] != (identity.tvdb_series_id, identity.tvdb_season):
        raise SelectionConflict()
    aid, _, _, anchor, backfill, following = plan
    in_window = (1 <= identity.tvdb_episode <= backfill
                 or following > 0 and anchor <= identity.tvdb_episode < anchor + following)
    if not in_window:
        raise SelectionConflict()
    recognized = db.execute(
        "SELECT 1 FROM recognized_episodes WHERE anidb_id=? AND tvdb_series_id=? "
        "AND tvdb_season=? AND tvdb_episode=? AND tvdb_episode_id=?",
        (aid, identity.tvdb_series_id, identity.tvdb_season,
         identity.tvdb_episode, identity.tvdb_episode_id)
    ).fetchone()
    if recognized is None:
        raise SelectionConflict()
    previous = db.execute(
        "SELECT tvdb_episode_id,info_hash FROM sonarr_episode_selections "
        "WHERE plan_id=? AND tvdb_episode=?", (plan_id, identity.tvdb_episode)
    ).fetchone()
    if previous is not None:
        if previous != (identity.tvdb_episode_id, digest):
            raise SelectionConflict()
        return False
    # The existing single and batch reservation namespaces remain authoritative.
    args = (identity.tvdb_series_id, identity.tvdb_season, identity.tvdb_episode)
    for table in ("episode_reservations", "batch_episode_reservations"):
        if db.execute(
            f"SELECT 1 FROM {table} WHERE state='ACTIVE' "
            "AND tvdb_series_id=? AND tvdb_season=? AND tvdb_episode=? LIMIT 1",
            args
        ).fetchone():
            raise SelectionConflict()
    if db.execute("SELECT 1 FROM sonarr_episode_selections WHERE plan_id=? AND info_hash=?",
                  (plan_id,digest)).fetchone():
        raise SelectionConflict()
    db.execute(
        "INSERT INTO sonarr_episode_selections "
        "(plan_id,tvdb_episode,tvdb_episode_id,info_hash,selected_at_ms) "
        "VALUES(?,?,?,?,?)",
        (plan_id,identity.tvdb_episode,identity.tvdb_episode_id,digest,
         time.time_ns()//1_000_000)
    )
    return True
