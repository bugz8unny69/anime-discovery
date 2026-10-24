"""Durable exact-episode gates in the worker's fenced completion transaction."""
import sqlite3
import time

from src.nextgen.episode_reservations import ReservationInput, ReservationConflict, EpisodeReserved
from src.nextgen.history import integer, append_job_history
from src.nextgen.storage.job_queue import QueueUnavailable
from src.nextgen.storage.migrations import LATEST_VERSION, MigrationError, _open
from src.nextgen.storage.releases import _source as release_source
from src.nextgen.storage.trials import _source as trial_source
from src.nextgen.trial_policy import Window, TrialConflict
from src.nextgen.release_contracts import ReleaseNotReady


def _facts(db,evaluation_job_id,event_id):
    row=db.execute("SELECT t.verification_id,t.plan_id,t.selected,t.reason_code,r.job_id,r.anidb_id,"
        "r.anidb_episode_id,r.tvdb_series_id,r.tvdb_season,r.tvdb_episode,r.tvdb_episode_id,"
        "r.identity_result_id,r.release_sha256,p.anidb_id,p.tvdb_series_id,p.tvdb_season,p.tvdb_order,"
        "p.anchor_episode,p.backfill_count,p.following_count,p.anchor_verification_id "
        "FROM trial_evaluations t JOIN jobs j ON j.job_id=t.job_id "
        "JOIN release_verifications r ON r.verification_id=t.verification_id "
        "JOIN trial_plans p ON p.plan_id=t.plan_id "
        "WHERE t.job_id=? AND j.event_id=? AND j.kind='EVALUATE_TRIAL' AND j.state='DONE'",
        (evaluation_job_id,event_id)).fetchone()
    if row is None:raise ReservationConflict()
    (verification,plan,selected,reason,release_job,aid,eid,tid,season,episode,tveid,
     identity,digest,plan_aid,plan_tid,plan_season,order,anchor,backfill,following,anchor_id)=row
    try:
        source=trial_source(db,release_job,event_id)
        original=release_source(db,event_id,aid)
        expected=episode in Window(backfill,following).episodes(anchor)
    except (TrialConflict,ReleaseNotReady,ValueError,TypeError):raise ReservationConflict() from None
    if (source.verification_id!=verification or original.identity_result_id!=identity or
            original.release_sha256!=digest or original.tvdb_series_id!=tid or
            (plan_aid,plan_tid,plan_season,order)!=(aid,tid,season,'official') or
            bool(selected)!=expected or reason!=('TRIAL_SELECTED' if expected else 'TRIAL_OUTSIDE_WINDOW')):
        raise ReservationConflict()
    anchor_row=db.execute("SELECT anidb_id,tvdb_series_id,tvdb_season,tvdb_episode,tvdb_order "
                          "FROM release_verifications WHERE verification_id=?",(anchor_id,)).fetchone()
    owner=db.execute('SELECT anidb_id FROM identified_episodes WHERE anidb_episode_id=?',(eid,)).fetchone()
    if anchor_row!=(aid,tid,season,anchor,'official') or owner!=(aid,):raise ReservationConflict()
    return ReservationInput(evaluation_job_id,event_id,verification,plan,aid,eid,tid,season,episode,tveid,expected)


def load_reservation_input(database,evaluation_job_id,event_id):
    integer(evaluation_job_id,positive=True)
    integer(event_id,positive=True)
    db=None
    try:
        db=_open(database,readonly=True,timeout_ms=5000)
        db.execute("BEGIN")
        if db.execute('PRAGMA user_version').fetchone()[0]!=LATEST_VERSION:raise QueueUnavailable()
        return _facts(db,evaluation_job_id,event_id)
    except (OSError,sqlite3.Error,MigrationError):raise QueueUnavailable() from None
    finally:
        if db is not None:db.close()


def persist_reservation(db,claim,value):
    """No commit, lease takeover, external action or whole-anime lock here."""
    if not db.in_transaction or type(value) is not ReservationInput:
        raise ValueError('worker transaction and verified episode facts required')
    if claim.event_id!=value.event_id or _facts(db,value.evaluation_job_id,claim.event_id)!=value:
        raise ReservationConflict()
    now=integer(time.time_ns()//1000000)
    if not value.selected:
        return append_job_history(db,job_id=claim.job_id,event_code='EPISODE_RESERVATION_SKIPPED',
            reason_code='TRIAL_OUTSIDE_WINDOW',component='worker',occurred_at_ms=now,details={'attempt':claim.attempt})
    key=(value.tvdb_series_id,value.tvdb_season,value.tvdb_episode)
    rows=db.execute("SELECT owner_job_id,evaluation_job_id,anidb_id,anidb_episode_id,"
                    "tvdb_series_id,tvdb_season,tvdb_episode,tvdb_episode_id FROM episode_reservations "
                    "WHERE state='ACTIVE' AND ((tvdb_series_id=? AND tvdb_season=? AND tvdb_episode=? AND tvdb_order='official') "
                    "OR anidb_episode_id=? OR tvdb_episode_id=?)",(*key,value.anidb_episode_id,value.tvdb_episode_id)).fetchall()
    expected=(value.anidb_id,value.anidb_episode_id,*key,value.tvdb_episode_id)
    prior=db.execute('SELECT state FROM episode_reservations WHERE owner_job_id=?',(claim.job_id,)).fetchone()
    if prior==('RELEASED',):raise ReservationConflict()
    if rows:
        if len(rows)!=1 or rows[0][2:]!=expected:raise ReservationConflict()
        if rows[0][0]!=claim.job_id:raise EpisodeReserved()
        if rows[0][1]!=value.evaluation_job_id:raise ReservationConflict()
    else:
        db.execute("INSERT INTO episode_reservations(owner_job_id,evaluation_job_id,verification_id,plan_id,"
            "anidb_id,anidb_episode_id,tvdb_series_id,tvdb_season,tvdb_episode,tvdb_episode_id,reserved_at_ms) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",(claim.job_id,value.evaluation_job_id,value.verification_id,value.plan_id,
            value.anidb_id,value.anidb_episode_id,*key,value.tvdb_episode_id,now))
    return append_job_history(db,job_id=claim.job_id,event_code='EPISODE_RESERVATION_CREATED',
        reason_code='EPISODE_RESERVATION_GRANTED',component='worker',occurred_at_ms=now,details={'attempt':claim.attempt})
