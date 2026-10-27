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


def activate_candidate(db, *, plan_id, episode, info_hash):
    """Activate only the next untried hash; caller still needs normal verification.

    A repeated activation of the same choice is idempotent. Fail closed when
    another candidate is already active or selection order changes.
    """
    if not db.in_transaction:
        raise CandidateConflict()
    digest=infohash(info_hash)
    active=db.execute(
        "SELECT info_hash FROM sonarr_episode_candidates "
        "WHERE plan_id=? AND tvdb_episode=? AND state='ACTIVE'",
        (plan_id,episode)).fetchall()
    if active:
        if active==[(digest,)]:
            return False
        raise CandidateConflict()
    next_row=next_candidate(db,plan_id=plan_id,episode=episode)
    if next_row is None or next_row[1]!=digest:
        raise CandidateConflict()
    changed=db.execute(
        "UPDATE sonarr_episode_candidates SET state='ACTIVE' "
        "WHERE plan_id=? AND tvdb_episode=? AND rank=? AND state='READY'",
        (plan_id,episode,next_row[0]))
    if changed.rowcount!=1:
        raise CandidateConflict()
    return True


def succeed_candidate(db, *, plan_id, episode, info_hash):
    """Mark a completed candidate only after existing staging has succeeded."""
    if not db.in_transaction:
        raise CandidateConflict()
    changed=db.execute(
        "UPDATE sonarr_episode_candidates SET state='SUCCEEDED' "
        "WHERE plan_id=? AND tvdb_episode=? AND info_hash=? AND state='ACTIVE'",
        (plan_id,episode,infohash(info_hash)))
    if changed.rowcount!=1:
        raise CandidateConflict()


def fail_candidate(db, *, plan_id, episode, info_hash, reason_code):
    """Only a previously active choice may become definitively failed."""
    if not db.in_transaction or type(reason_code) is not str or not reason_code:
        raise CandidateConflict()
    result=db.execute(
        "UPDATE sonarr_episode_candidates SET state='FAILED',reason_code=? "
        "WHERE plan_id=? AND tvdb_episode=? AND info_hash=? AND state='ACTIVE'",
        (reason_code,plan_id,episode,infohash(info_hash)))
    if result.rowcount!=1:raise CandidateConflict()

def mark_published(db, *, event_id, info_hash):
    """Complete the active choice only for a verified, staged Sonarr event.

    Caller has already published media and marked the operation STAGED in the
    same worker transaction. Ordinary non-Sonarr staging is unaffected.
    """
    if not db.in_transaction:
        raise CandidateConflict()
    digest=infohash(info_hash)
    rows=db.execute(
        "SELECT c.plan_id,c.tvdb_episode FROM incoming_events e "
        "JOIN jobs verify ON verify.event_id=e.event_id AND verify.kind='VERIFY_RELEASE' "
        "JOIN jobs parent ON parent.job_id=verify.created_by_job_id "
        " AND parent.kind='DISCOVER_SONARR_BACKFILL' "
        "JOIN trial_plans p ON p.plan_id=json_extract(parent.payload_json,'$.plan_id') "
        "JOIN sonarr_episode_selections s ON s.plan_id=p.plan_id AND s.info_hash=? "
        "JOIN sonarr_episode_candidates c ON c.plan_id=s.plan_id "
        " AND c.tvdb_episode=s.tvdb_episode AND c.info_hash=? AND c.state='ACTIVE' "
        "WHERE e.event_id=? AND e.source='sonarr-discovery'",
        (digest,digest,event_id)).fetchall()
    if not rows:
        return False
    if len(rows)!=1:
        raise CandidateConflict()
    plan_id,episode=rows[0]
    succeed_candidate(db,plan_id=plan_id,episode=episode,info_hash=digest)
    return True


def schedule_after_cleanup(db,operation_id):
    """Only a reviewed, fully cleaned Sonarr attempt advances the ranked list.

    A user cancel without a terminal review never triggers another download.
    The next choice is re-fetched by the existing Sonarr discovery worker.
    """
    if not db.in_transaction:raise CandidateConflict()
    issue=db.execute(
        "SELECT h.reason_code FROM job_history h "
        "JOIN job_operation_members m ON m.job_id=h.job_id "
        "WHERE m.operation_id=? AND h.event_code='NEEDS_REVIEW' "
        "ORDER BY h.history_id DESC LIMIT 1",(operation_id,)).fetchone()
    if issue is None:return ()
    rows=db.execute(
        "SELECT s.plan_id,s.tvdb_episode,s.info_hash,parent.event_id,parent.job_id "
        "FROM job_operation_members m "
        "JOIN jobs verify ON verify.job_id=m.job_id AND verify.kind='VERIFY_RELEASE' "
        "JOIN incoming_events e ON e.event_id=verify.event_id "
        "AND e.source='sonarr-discovery' "
        "JOIN jobs parent ON parent.job_id=verify.created_by_job_id "
        "AND parent.kind='DISCOVER_SONARR_BACKFILL' "
        "JOIN trial_plans p ON p.plan_id=json_extract(parent.payload_json,'$.plan_id') "
        "JOIN sonarr_episode_selections s ON s.plan_id=p.plan_id "
        "JOIN sonarr_episode_candidates c ON c.plan_id=s.plan_id "
        "AND c.tvdb_episode=s.tvdb_episode AND c.info_hash=s.info_hash "
        "AND c.state='ACTIVE' "
        "WHERE m.operation_id=? "
        "AND s.info_hash=json_extract(CAST(e.raw_body AS TEXT),'$.torrent_infohash')",
        (operation_id,)).fetchall()
    if not rows:return ()
    if len(rows)!=1:raise CandidateConflict()
    plan_id,episode,digest,parent_event,parent_job=rows[0]
    if parent_event is None:raise CandidateConflict()
    # CancellationService has already confirmed cleanup and released all
    # reservations inside this transaction. Never advance before that point.
    if db.execute(
        "SELECT 1 FROM episode_reservations r "
        "JOIN acquisition_plans p USING(reservation_id) "
        "WHERE p.info_hash=? AND r.state='ACTIVE' LIMIT 1",
        (digest,)).fetchone():
        raise CandidateConflict()
    fail_candidate(db,plan_id=plan_id,episode=episode,info_hash=digest,
                   reason_code=issue[0] or 'JOB_RETRY_EXHAUSTED')
    pending=next_candidate(db,plan_id=plan_id,episode=episode)
    if pending is None:return ()
    from src.nextgen.storage.sqlite import enqueue_job_with_receipt
    from src.nextgen.storage.sonarr_backfill import PAGE_SIZE
    page_start=((episode-1)//PAGE_SIZE)*PAGE_SIZE+1
    _,receipt=enqueue_job_with_receipt(
        db,kind='DISCOVER_SONARR_BACKFILL',
        payload={'plan_id':plan_id,'start':page_start,
                 'fallback_episode':episode},
        component='worker',event_id=parent_event,
        created_by_job_id=parent_job)
    return (receipt,)
