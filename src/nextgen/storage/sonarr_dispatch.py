"""Trusted internal Sonarr delivery, routed into the ORIGINAL acquisition pipeline.

Called only in the Sonarr backfill worker's fenced SQLite completion transaction.
No download, extra torrent submission implementation, or caller-supplied event.
"""
import json
import time

from src.nextgen.acquisition.sonarr_search import CandidateSelection
from src.nextgen.history import append_event_history
from src.nextgen.job_contracts import parse_payload
from src.nextgen.storage.sqlite import enqueue_job_with_receipt, persist_identity
from src.nextgen.storage.sonarr_selection import SelectionConflict


def dispatch(db, claim, plan, choice):
    """Turn one verified source choice into an auditable internal delivery.

    Identity is copied from the episode's *already verified* source and
    revalidated by persist_identity. The normal VERIFY_RELEASE handler still
    checks the Sonarr title against the recognized episode before reservation.
    """
    if (not db.in_transaction or type(choice) is not CandidateSelection
            or claim.event_id is None or claim.kind != 'DISCOVER_SONARR_BACKFILL'
            or choice.identity.tvdb_series_id != plan.tvdb_series_id
            or choice.identity.tvdb_season != plan.season):
        raise SelectionConflict()
    identity=choice.identity
    row=db.execute(
        "SELECT i.series_json, r.anidb_episode_number "
        "FROM recognized_episodes e "
        "JOIN release_verifications r ON r.verification_id=e.evidence_verification_id "
        "JOIN identity_results i ON i.result_id=r.identity_result_id "
        "WHERE e.anidb_id=? AND e.tvdb_series_id=? AND e.tvdb_season=? "
        "AND e.tvdb_episode=? AND e.tvdb_episode_id=? "
        "AND r.anidb_id=e.anidb_id AND r.tvdb_series_id=e.tvdb_series_id "
        "AND r.tvdb_episode_id=e.tvdb_episode_id",
        (plan.anidb_id,identity.tvdb_series_id,identity.tvdb_season,
         identity.tvdb_episode,identity.tvdb_episode_id)).fetchone()
    if row is None: raise SelectionConflict()
    try:
        # The release declaration is rechecked by VERIFY_RELEASE and then the
        # manifest filename gate before any stopped submission is authorized.
        from src.nextgen.providers.release_mapping import declared_episode
        origin,season,episode=declared_episode(choice.release.title)
        if ((origin=='tvdb' and (season,episode)!=(identity.tvdb_season,identity.tvdb_episode))
                or (origin=='anidb' and episode!=row[1])):
            raise SelectionConflict()
        validated=parse_payload(row[0])
        if validated.get('anime',{}).get('anidb_id')!=plan.anidb_id:
            raise SelectionConflict()
        body=json.dumps({'release_name':choice.release.title,
                         'torrent_infohash':choice.release.info_hash},
                        sort_keys=True,separators=(',',':')).encode('utf-8')
        if len(body)>65536: raise SelectionConflict()
    except (ValueError,TypeError,KeyError,AttributeError):
        raise SelectionConflict() from None
    op=db.execute("SELECT operation_id FROM job_operation_members WHERE job_id=?",
                  (claim.job_id,)).fetchone()
    if op is None: raise SelectionConflict()
    now=time.time_ns()//1_000_000
    event_id=db.execute(
        "INSERT INTO incoming_events(source,raw_body,received_at_ms) VALUES(?,?,?)",
        ('sonarr-discovery',body,now)).lastrowid
    receipt=append_event_history(db,event_id=event_id,event_code='ACCEPTED',
                                 component='worker',occurred_at_ms=now)
    # Publish already verified anime identity for the NEW, transparently
    # marked delivery. It is NOT a copy of the old torrent or old event.
    _,audit=persist_identity(db,event_id,validated,validated_at_ms=now)
    job_id,created=enqueue_job_with_receipt(
        db,kind='VERIFY_RELEASE',payload={'anidb_id':plan.anidb_id},
        component='worker',event_id=event_id,created_by_job_id=claim.job_id,
        operation_id=op[0])
    return (receipt, *((audit,) if audit is not None else ()), created)
