"""Durable missing-position search batches, without invented episode identities.

Prowlarr results are search hints, not torrent authorizations. A ticket is
inserted only on the worker's fenced DONE transaction; concurrent deliveries
are deduplicated by (plan_id, official TVDB episode) and infohash. No release
verification, reservation or download may bypass the Intake pipeline.
"""
from dataclasses import dataclass
import sqlite3
import time

from src.nextgen.history import integer
from src.nextgen.trial_policy import Window
from src.nextgen.storage.migrations import _open,LATEST_VERSION
from src.nextgen.storage.job_queue import QueueUnavailable
from src.nextgen.storage.review_decisions import require_allowed


class SearchReview(ValueError):
    reason_code="MISSING_SEARCH_INVALID"
    def __init__(self):super().__init__("This missing-episode search cannot be reconciled with its trial plan.")


@dataclass(frozen=True)
class Batch:
    evaluation_job_id: int
    event_id: int
    plan_id: int
    anidb_id: int
    series_id: int
    season: int
    title: str
    episodes: tuple
    has_more: bool

    def __post_init__(self):
        for x in (self.evaluation_job_id,self.event_id,self.plan_id,self.anidb_id,self.series_id):
            integer(x,positive=True)
        if type(self.season) is not int or not 0<=self.season<=999:
            raise SearchReview()
        if type(self.title) is not str or not 1<=len(self.title)<=512:raise SearchReview()
        if type(self.episodes) is not tuple or len(self.episodes)>8 or type(self.has_more) is not bool:
            raise SearchReview()


@dataclass(frozen=True)
class Results:
    batch: Batch
    matches: tuple  # ((tvdb_episode, ((sha1, release_name), ...)), ...)
    search_job_id: int

    def __post_init__(self):
        integer(self.search_job_id,positive=True)
        if type(self.batch) is not Batch or type(self.matches) is not tuple:
            raise SearchReview()
        if tuple(e for e,_ in self.matches)!=self.batch.episodes:raise SearchReview()
        for _,candidates in self.matches:
            if type(candidates) is not tuple or len(candidates)>25:raise SearchReview()


def _batch(db,evaluation_job_id,event_id):
    row=db.execute("SELECT p.plan_id,p.anidb_id,p.tvdb_series_id,p.tvdb_season,"
        "p.anchor_episode,p.backfill_count,p.following_count,a.title "
        "FROM trial_evaluations t JOIN trial_plans p ON p.plan_id=t.plan_id "
        "JOIN jobs j ON j.job_id=t.job_id "
        "JOIN identified_anime a ON a.anidb_id=p.anidb_id "
        "WHERE t.job_id=? AND j.event_id=? AND j.kind='EVALUATE_TRIAL' AND j.state='DONE' "
        "AND p.tvdb_order='official' AND p.tvdb_series_id=a.tvdb_series_id",
        (evaluation_job_id,event_id)).fetchone()
    if row is None:raise SearchReview()
    plan,aid,tid,season,anchor,backfill,following,title=row
    require_allowed(db,aid)
    positions=Window(backfill,following).episodes(anchor)
    # Reserved positions (including trial-stage/Keep owners) are NOT missing.
    reserved={x[0] for x in db.execute(
        "SELECT tvdb_episode FROM episode_reservations WHERE tvdb_series_id=? "
        "AND tvdb_season=? AND tvdb_order='official'",(tid,season))}
    # A separately verified incoming release for this AniDB entry already
    # supplies a candidate to the regular queue, even before reservation.
    known={x[0] for x in db.execute(
        "SELECT tvdb_episode FROM release_verifications WHERE anidb_id=? "
        "AND tvdb_series_id=? AND tvdb_season=? AND tvdb_order='official'",
        (aid,tid,season))}
    searched={x[0] for x in db.execute(
        "SELECT tvdb_episode FROM missing_episode_searches WHERE plan_id=?",(plan,))}
    left=[n for n in positions if n not in reserved and n not in known and n not in searched]
    return Batch(evaluation_job_id,event_id,plan,aid,tid,season,title,
                 tuple(left[:8]),len(left)>8)


def load(database, evaluation_job_id, event_id):
    integer(evaluation_job_id,positive=True);integer(event_id,positive=True)
    db=None
    try:
        db=_open(database,readonly=True)
        if db.execute("PRAGMA user_version").fetchone()[0]!=LATEST_VERSION:
            raise QueueUnavailable()
        return _batch(db,evaluation_job_id,event_id)
    except (sqlite3.Error,OSError):
        raise QueueUnavailable() from None
    finally:
        if db is not None:db.close()


def persist(db,claim,result):
    """Persist only the batch that the verified worker actually searched."""
    if not db.in_transaction or type(result) is not Results or result.search_job_id!=claim.job_id:
        raise SearchReview()
    original=result.batch
    if original.event_id!=claim.event_id:
        raise SearchReview()
    # Reload plan identity under the worker lease; concurrent search jobs may
    # have recorded a target while this batch was contacting the indexer.
    current=_batch(db,original.evaluation_job_id,claim.event_id)
    if (current.plan_id,current.anidb_id,current.series_id,current.season,current.title)!=(
        original.plan_id,original.anidb_id,original.series_id,original.season,original.title):
        raise SearchReview()
    now=integer(time.time_ns()//1000000)
    for episode,candidates in result.matches:
        if type(episode) is not int or episode not in original.episodes:raise SearchReview()
        if db.execute("SELECT 1 FROM episode_reservations WHERE tvdb_series_id=? "
                      "AND tvdb_season=? AND tvdb_episode=? AND tvdb_order='official'",
                      (original.series_id,original.season,episode)).fetchone():
            continue  # Acquired by concurrent Intake; don't claim missing.
        inserted=db.execute("INSERT OR IGNORE INTO missing_episode_searches "
            "(plan_id,tvdb_episode,search_job_id,status,candidate_count,searched_at_ms) "
            "VALUES(?,?,?,?,?,?)",(original.plan_id,episode,claim.job_id,
               'FOUND' if candidates else 'NO_MATCH',len(candidates),now)).rowcount
        if not inserted:continue
        for digest,title in candidates:
            if (type(digest) is not str or len(digest)!=40 or
                    any(c not in "0123456789abcdef" for c in digest)
                    or type(title) is not str or not 1<=len(title)<=1024):
                raise SearchReview()
            db.execute("INSERT INTO missing_episode_candidates "
                "(plan_id,tvdb_episode,info_hash,release_name,discovered_at_ms) "
                "VALUES(?,?,?,?,?)",(original.plan_id,episode,digest,title,now))
