"""One-shot series episode-gap discovery shared by Autobrr and manual requests.

Discovery searches available Prowlarr releases once, filters out episodes
already staged or in flight, and hands verified candidates to the same
receive/approve/claimed-acquisition path used by Autobrr.
"""
import asyncio
import json
import sqlite3
import time
from pathlib import Path

from anime_async_daemon import enqueue
from anime_prowlarr_search import candidates
from anime_webhook_processing import receive
from anime_trial_policy import window_for, eligibility, journal


def identity_for_request(series_map,*,title=None,tvdb_id=None,anidb_id=None):
    """Resolve a request only from known, unambiguous configured identity."""
    matches=[]
    for alias,entry in series_map.items():
        if title and title.casefold().strip()!=alias.casefold().strip():
            continue
        if tvdb_id and str(entry["tvdb_id"])!=str(tvdb_id):
            continue
        if anidb_id and str(entry["anidb_id"])!=str(anidb_id):
            continue
        matches.append((alias,entry))
    identities={(str(e["tvdb_id"]),str(e["anidb_id"])) for _,e in matches}
    if len(identities)!=1 or not matches:
        raise ValueError("No unique known TVDB/AniDB mapping; add a recognized name first")
    alias,entry=matches[0]
    return {"title":alias,"tvdb_id":str(entry["tvdb_id"]),
            "anidb_id":str(entry["anidb_id"])}


def schedule(db,*,title,tvdb_id,anidb_id,season=1,up_to=None,origin="manual"):
    if origin not in ("manual","autobrr"):
        raise ValueError("Unsupported request source")
    if not isinstance(title,str) or not title.strip() or len(title)>200:
        raise ValueError("Title required")
    if not str(tvdb_id).isdigit() or int(tvdb_id)<=0 or not str(anidb_id).isdigit() or int(anidb_id)<=0:
        raise ValueError("Verified TVDB and AniDB identity required")
    if type(season) is not int or not 1<=season<=100:
        raise ValueError("Invalid anime season")
    if up_to is not None and (type(up_to) is not int or not 1<=up_to<=500):
        raise ValueError("Invalid latest episode")
    existing=db.execute("SELECT id,status FROM series WHERE source='tvdb' AND external_id=?",
                        (str(int(tvdb_id)),)).fetchone()
    if existing:
        if existing[1]=="REJECTED" or db.execute(
            "SELECT 1 FROM series_rejection_blocks WHERE series_id=?",(existing[0],)).fetchone():
            raise ValueError("Series rejected")
        if db.execute("SELECT 1 FROM series_quarantine WHERE series_id=?",(existing[0],)).fetchone():
            raise ValueError("Series quarantined")
    payload=json.dumps({"title":title,"tvdb_id":str(int(tvdb_id)),"anidb_id":str(int(anidb_id)),
                        "season":season,"up_to":up_to,"origin":origin},sort_keys=True)
    # Autobrr's first received episode triggers one bounded catch-up search.
    # Manual submissions each create a single explicitly requested search.
    if origin=="autobrr":
        key="autobrr:%s:%s:%s"%(tvdb_id,season,up_to)
    else:
        import uuid
        key="manual:"+uuid.uuid4().hex
    enqueue(db,"series_gap_search",key,payload)
    return {"queued":True,"source":origin,"subject_key":key}


def search_once(db,request,client):
    title=request["title"]
    tvdb_id=request["tvdb_id"]
    anidb_id=request["anidb_id"]
    season=request["season"]
    upper=request["up_to"]
    origin=request["origin"]
    window=window_for(db,tvdb_id=tvdb_id,anidb_id=anidb_id,season=season)
    # The webhook episode is a search trigger, not permission to acquire it.
    # Never backfill beyond the verified six-episode window.
    bound=min(upper,window["end"]) if upper is not None else window["end"]
    if bound < window["start"]:
        journal("BACKFILL_SKIPPED",reason="TRIGGER_BEFORE_TRIAL",tvdb_id=tvdb_id,
                season=season,episode=upper,start=window["start"],end=window["end"])
        return {"state":"DONE","queued":0}
    existing=db.execute("SELECT id,status FROM series WHERE source='tvdb' AND external_id=?",
                        (tvdb_id,)).fetchone()
    if existing:
        sid,state=existing
        if state=="REJECTED" or db.execute(
            "SELECT 1 FROM series_rejection_blocks WHERE series_id=?",(sid,)).fetchone():
            return {"state":"BLOCKED","reason":"Series rejected"}
        if db.execute("SELECT 1 FROM series_quarantine WHERE series_id=?",(sid,)).fetchone():
            return {"state":"BLOCKED","reason":"Series quarantined"}
    matches=candidates(client.search(title),alias=title,tvdb_id=tvdb_id,
                       anidb_id=anidb_id,season=season,max_episode=bound)
    queued=0
    for release in matches:
        episode=release["episode"]
        policy=eligibility(db,tvdb_id=tvdb_id,anidb_id=anidb_id,
                           season=season,episode=episode)
        if not policy["eligible"] or episode > bound:
            continue
        if existing:
            rows=db.execute("""SELECT d.state,r.staged_path
                FROM episode_dispatch d
                LEFT JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
                WHERE d.series_id=? AND d.season=? AND d.episode=?""",
                (existing[0],season,episode)).fetchall()
            if any(state in ("CLAIMED","NEEDS_REVIEW") or
                   (state=="DONE" and path and Path(path).is_file())
                   for state,path in rows):
                journal("BACKFILL_SKIPPED",reason="ALREADY_RESERVED",tvdb_id=tvdb_id,
                        season=season,episode=episode,start=window["start"],
                        end=window["end"])
                continue
        # A Prowlarr result enters the same verified episode acquisition path.
        result=receive(db,{"source":origin,
            "source_guid":"prowlarr:"+release["info_hash"],
            "release_name":release["release_name"],
            "info_hash":release["info_hash"],
            "magnet_uri":release["magnet_uri"],
            "tvdb_id":tvdb_id,"anidb_id":anidb_id,
            "season":season,"episode":episode})
        queued+=bool(result.get("queued"))
        journal("BACKFILL_DECISION",
                reason="QUEUED" if result.get("queued") else "DUPLICATE_OR_SKIPPED",
                tvdb_id=tvdb_id,season=season,episode=episode,
                start=window["start"],end=window["end"])
    return {"state":"DONE","queued":queued}


def handler_factory(db_path,client_factory):
    async def handle(job):
        try:
            request=json.loads(job["payload_json"])
            if set(request)!={"title","tvdb_id","anidb_id","season","up_to","origin"}:
                return "NEEDS_REVIEW"
            def execute():
                with sqlite3.connect(db_path,isolation_level=None,timeout=10) as db:
                    db.execute("PRAGMA foreign_keys=ON")
                    db.execute("PRAGMA busy_timeout=10000")
                    return search_once(db,request,client_factory())
            result=await asyncio.to_thread(execute)
            return result["state"]
        except (ValueError,KeyError,TypeError,json.JSONDecodeError):
            return "NEEDS_REVIEW"
    return handle
