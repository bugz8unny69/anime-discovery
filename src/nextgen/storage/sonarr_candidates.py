"""Ranked Sonarr candidate facts, not acquisition permits or torrent ownership."""
from src.nextgen.acquisition.metadata import infohash
from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, SearchResult


class CandidateConflict(ValueError):
    reason_code='SONARR_SELECTION_CONFLICT'


def save_candidates(db, *, plan_id, episode, result, policy):
    """Save eligible hashes once in a fenced write transaction; no source URLs.

    Replays must be identical. Another source cannot silently replace evidence.
    """
    if (not db.in_transaction or type(plan_id) is not int or plan_id <= 0
            or type(episode) is not int or episode <= 0 or episode > 1000
            or type(result) is not SearchResult or type(policy) is not DiscoveryPolicy):
        raise CandidateConflict()
    hashes=[]
    for release in policy.rank(result.candidates):
        if policy.accepts(release):
            try: digest=infohash(release.info_hash)
            except ValueError: raise CandidateConflict() from None
            if digest not in hashes:
                hashes.append(digest)
    previous=db.execute(
        "SELECT info_hash FROM sonarr_episode_candidates WHERE plan_id=? AND tvdb_episode=? ORDER BY rank",
        (plan_id,episode)).fetchall()
    if previous:
        if [row[0] for row in previous] != hashes:
            raise CandidateConflict()
        return False
    for rank,digest in enumerate(hashes,1):
        db.execute(
            "INSERT INTO sonarr_episode_candidates(plan_id,tvdb_episode,rank,info_hash) VALUES(?,?,?,?)",
            (plan_id,episode,rank,digest))
    return bool(hashes)


def next_candidate(db, *, plan_id, episode):
    """Read-only next candidate; selection does not grant a send permit."""
    row=db.execute(
        "SELECT rank,info_hash FROM sonarr_episode_candidates WHERE plan_id=? "
        "AND tvdb_episode=? AND state='READY' ORDER BY rank LIMIT 1",
        (plan_id,episode)).fetchone()
    return row


def fail_candidate(db, *, plan_id, episode, info_hash, reason_code):
    """Only a previously active choice may become definitively failed."""
    if not db.in_transaction or type(reason_code) is not str or not reason_code:
        raise CandidateConflict()
    result=db.execute(
        "UPDATE sonarr_episode_candidates SET state='FAILED',reason_code=? "
        "WHERE plan_id=? AND tvdb_episode=? AND info_hash=? AND state='ACTIVE'",
        (reason_code,plan_id,episode,infohash(info_hash)))
    if result.rowcount!=1:raise CandidateConflict()
