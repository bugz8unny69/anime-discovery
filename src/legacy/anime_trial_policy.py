"""Immutable six-episode trial windows and journal-friendly decision reasons.

A regular verified season defaults to E01-E06. New part/cour and ongoing
windows must be created by a *trusted provider identity/airing verifier*;
neither a torrent title nor an Autobrr webhook may choose the window.
No service calls, torrent writes or logs with tokens/magnet URIs.
"""
import logging
import re
import time

LOG = logging.getLogger("anime_discovery.trial")
MODES = frozenset(("SEASON", "PART", "ONGOING"))
_EVIDENCE = re.compile(r"^[A-Za-z0-9:._/-]{1,160}$")
_UNIT = re.compile(r"^[a-zA-Z0-9:_-]{1,90}$")


def journal(event, *, reason, tvdb_id, season, episode=None, start=None,
            end=None, infohash=None):
    """One structured, grep-friendly journald line; no raw release content."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,50}",event):
        raise ValueError("Invalid journal event name")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,60}",reason):
        raise ValueError("Invalid journal reason code")
    hash_tag = (str(infohash)[:12] if infohash else "-")
    LOG.info("event=%s reason=%s tvdb=%s season=%s episode=%s window=%s-%s torrent=%s",
             event,reason,tvdb_id,season,episode if episode is not None else "-",
             start if start is not None else "-",
             end if end is not None else "-",hash_tag)


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_trial_windows (
        tvdb_id TEXT NOT NULL,
        anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL CHECK(season>=1),
        unit_key TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('SEASON','PART','ONGOING')),
        start_episode INTEGER NOT NULL CHECK(start_episode>=1),
        end_episode INTEGER NOT NULL CHECK(end_episode>=start_episode),
        evidence_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY(tvdb_id, season, unit_key)
    )""")


def _identity(tvdb_id, anidb_id, season):
    if (not str(tvdb_id).isdigit() or int(tvdb_id) <= 0
            or not str(anidb_id).isdigit() or int(anidb_id) <= 0
            or type(season) is not int or not 1 <= season <= 100):
        raise ValueError("Verified positive series IDs and season required")
    return str(int(tvdb_id)), str(int(anidb_id))


def record_verified_window(db, *, tvdb_id, anidb_id, season, unit_key,
                           mode, start_episode, evidence_ref):
    """Record an immutable policy decision after independent verification.

    The privileged caller must validate the provider episode/part boundary
    and store an auditable evidence reference first. This function does NOT
    independently verify that evidence and must never be wired to a raw
    webhook, release title, or user-supplied request.
    """
    tvdb_id, anidb_id = _identity(tvdb_id, anidb_id, season)
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    if mode not in MODES or not isinstance(unit_key,str) or not _UNIT.fullmatch(unit_key):
        raise ValueError("Invalid verified trial unit")
    if (type(start_episode) is not int or not 1 <= start_episode <= 9999
            or start_episode > 9994 or
            not isinstance(evidence_ref,str) or not _EVIDENCE.fullmatch(evidence_ref)):
        raise ValueError("Invalid episode boundary or evidence reference")
    if mode == "SEASON" and (start_episode != 1 or unit_key != "season"):
        raise ValueError("New regular season starts at canonical E01")
    if mode == "ONGOING" and start_episode == 1:
        raise ValueError("Ongoing discovery window requires a verified non-E01 anchor")
    end_episode = start_episode + 5
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        previous = db.execute("""SELECT anidb_id,mode,start_episode,end_episode,evidence_ref
            FROM anime_trial_windows WHERE tvdb_id=? AND season=? AND unit_key=?""",
            (tvdb_id,season,unit_key)).fetchone()
        proposed=(anidb_id,mode,start_episode,end_episode,evidence_ref)
        if previous and tuple(previous) != proposed:
            raise ValueError("Verified trial window already exists with conflicting boundary")
        if not previous:
            db.execute("INSERT INTO anime_trial_windows VALUES (?,?,?,?,?,?,?,?,?)",
                (tvdb_id,anidb_id,season,unit_key,mode,start_episode,end_episode,
                 evidence_ref,int(time.time())))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    if not previous:
        journal("WINDOW_LOCKED",reason="VERIFIED_BOUNDARY",tvdb_id=tvdb_id,
                season=season,start=start_episode,end=end_episode)
    return {"tvdb_id":tvdb_id,"anidb_id":anidb_id,"season":season,
            "unit_key":unit_key,"mode":mode,"start":start_episode,
            "end":end_episode,"evidence_ref":evidence_ref}


def window_for(db, *, tvdb_id, anidb_id, season, unit_key=None):
    """Use an existing unique verified window, else regular-season E01-E06.

    Multiple units inside a provider season (e.g., Part 1 and Part 2)
    cannot be chosen safely from the torrent filename or a webhook.
    An upstream verified unit binding is required before such automation.
    """
    tvdb_id, anidb_id = _identity(tvdb_id,anidb_id,season)
    ensure_schema(db)
    rows=db.execute("""SELECT anidb_id,unit_key,mode,start_episode,end_episode,evidence_ref
        FROM anime_trial_windows WHERE tvdb_id=? AND season=?""",
        (tvdb_id,season)).fetchall()
    if unit_key is not None:
        if not isinstance(unit_key,str) or not _UNIT.fullmatch(unit_key):
            raise ValueError("Invalid verified trial unit")
        rows=[row for row in rows if row[1]==unit_key]
        if not rows:
            raise ValueError("Requested verified trial unit not found")
    if not rows:
        return {"tvdb_id":tvdb_id,"anidb_id":anidb_id,
                "season":season,"unit_key":"season","mode":"SEASON",
                "start":1,"end":6,"evidence_ref":None}
    if len(rows) != 1 or rows[0][0] != anidb_id:
        raise ValueError("Ambiguous or conflicting verified trial windows")
    aid,unit,mode,start,end,evidence=rows[0]
    return {"tvdb_id":tvdb_id,"anidb_id":aid,"season":season,
            "unit_key":unit,"mode":mode,"start":start,"end":end,
            "evidence_ref":evidence}


def eligibility(db, *, tvdb_id, anidb_id, season, episode):
    """Decide one inbound or backfill episode, never mutate torrents."""
    if type(episode) is not int or episode < 1:
        raise ValueError("Positive canonical episode required")
    window=window_for(db,tvdb_id=tvdb_id,anidb_id=anidb_id,season=season)
    eligible=window["start"] <= episode <= window["end"]
    reason="INSIDE_TRIAL_WINDOW" if eligible else "OUTSIDE_TRIAL_WINDOW"
    journal("EPISODE_ELIGIBILITY",reason=reason,tvdb_id=window["tvdb_id"],
            season=season,episode=episode,start=window["start"],end=window["end"])
    return {"eligible":eligible,"reason":reason,"window":window}
