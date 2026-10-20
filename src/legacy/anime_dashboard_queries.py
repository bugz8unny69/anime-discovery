"""Dashboard queries: staged Anime-Trial library and live acquisition jobs.

Series visibility comes from successful staging records, not from merely
recognizing a title in an incoming release. Pagination is applied after
verifying staged files still exist on disk.
"""
from pathlib import Path
import json
from anime_job_management import latest_events

PAGE_SIZES=(20,50,100)


def pagination(page=1, size=20):
    try:
        page,size=int(page),int(size)
    except (TypeError,ValueError) as exc:
        raise ValueError("Invalid pagination") from exc
    if page<1 or size not in PAGE_SIZES:
        raise ValueError("Page must be positive; page size must be 20, 50 or 100")
    return page,size


def _page(items,page,size):
    total=len(items)
    pages=max(1,(total+size-1)//size)
    page=min(page,pages)
    return {"items":items[(page-1)*size:page*size],
            "page":page,"page_size":size,"total":total,"pages":pages}


def staged_series(db, *, page=1,size=20):
    """Show only series with at least one staged episode still on disk."""
    page,size=pagination(page,size)
    records=db.execute("""SELECT s.id,s.title,s.external_id,s.status,
        d.season,d.episode,r.staged_path
        FROM series s
        JOIN episode_dispatch d ON d.series_id=s.id AND d.state='DONE'
        JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
        WHERE s.source='tvdb'
        ORDER BY lower(s.title),s.id,d.season,d.episode""").fetchall()
    grouped={}
    for sid,title,tvdb,status,season,episode,path in records:
        if not path or not Path(path).is_file():
            continue
        if sid not in grouped:
            grouped[sid]={"id":sid,"title":title,"tvdb_id":tvdb,
                          "status":status,"staged_episodes":0,"latest_episode":""}
        grouped[sid]["staged_episodes"]+=1
        grouped[sid]["latest_episode"]="S%02dE%02d"%(season,episode)
    return _page(list(grouped.values()),page,size)


def all_jobs(db, *,page=1,size=20):
    """One activity entry per incoming release including unmatched webhook events."""
    page,size=pagination(page,size)
    events=latest_events(db)
    identity_checks={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_identity_checks'").fetchone():
        for nid,decision,document in db.execute(
                "SELECT notification_id,decision,evidence_json FROM unified_identity_checks"):
            try:
                evidence=json.loads(document)
                codes=evidence.get("issues") or []
                safe_codes=[x for x in codes if isinstance(x,str) and
                    len(x)<=100 and all(c.isalnum() or c=="_" for c in x)]
                identity_checks[nid]=(decision,safe_codes[:3])
            except (TypeError,ValueError):
                identity_checks[nid]=("UNKNOWN",[])
    rows=db.execute("""SELECT n.id,n.source,n.release_name,n.received_at,n.status,
        d.season,d.episode,d.state,
        j.state,j.last_error,r.staged_path,
        COALESCE(s.title,'')
        FROM notifications n
        LEFT JOIN episode_dispatch d ON d.notification_id=n.id
        LEFT JOIN series s ON s.id=d.series_id
        LEFT JOIN daemon_jobs j ON j.kind='claimed_acquisition'
             AND j.subject_key=CAST(n.id AS TEXT)
        LEFT JOIN torrent_recovery_records r ON r.notification_id=n.id
        ORDER BY n.id DESC""").fetchall()
    result=[]
    for nid,source,release,received,nstatus,season,episode,dispatch,job_id,job,attempts,retry_at,lease_until,error,stage,title in rows:
        event=events.get(job_id)
        canceled=job=="BLOCKED" and event is not None and event["action"]=="cancel"
        if canceled:
            status="CANCELED"
        elif job=="DONE" and dispatch=="DONE":
            status="COMPLETED"
        elif job=="LEASED":
            status="RUNNING"
        elif job=="READY":
            status="QUEUED"
        elif job=="DEFERRED":
            status="WAITING FOR DOWNLOAD"
        elif job=="BLOCKED":
            status="BLOCKED"
        elif job=="NEEDS_REVIEW" or dispatch=="NEEDS_REVIEW":
            status="NEEDS REVIEW"
        elif job=="DONE":
            status="COMPLETED"
        elif dispatch=="CLAIMED":
            status="QUEUED"
        elif nstatus=="IDENTIFYING":
            status="IDENTIFYING"
        elif nstatus=="NEEDS_REVIEW" and not dispatch:
            status="NEEDS REVIEW"
        else:
            status="RECEIVED"
        # An unmatched intake record is not an acquisition job. Make that
        # distinction visible instead of suggesting an idle worker.
        if status in ("RECEIVED","NEEDS REVIEW"):
            explanation=("Identity check finished; manual review is required. No acquisition job was created. "
                         "Recognize the title or approve notification #"+str(nid)+" with TVDB/AniDB IDs and episode.")
        elif status=="IDENTIFYING":
            explanation="Checking public AniDB titles and TVDB links. Identity is still in progress; NTFY alerts follow the finalized review status."
        elif status=="QUEUED":
            explanation="Acquisition job queued; waiting for a worker."
        elif status=="RUNNING":
            explanation="Acquisition worker has leased this job."
        elif status=="COMPLETED":
            explanation="Acquisition job completed."
        elif status=="CANCELED":
            explanation="Canceled by an administrator. The job will not be retried; no torrent or media was deleted."
        else:
            explanation=error or ("Current job state: "+status.lower())
        if status in ("IDENTIFYING","NEEDS REVIEW") and nid in identity_checks:
            decision,codes=identity_checks[nid]
            explanation+=" Latest identity check: "+str(decision)[:80]
            if codes:
                explanation+="; "+", ".join(codes)
        result.append({"id":nid,"job_id":job_id,"job_state":job,"attempts":attempts,
                        "next_retry_at":retry_at if job=="DEFERRED" else None,
                        "lease_until":lease_until if job=="LEASED" else None,
                        "last_error":error or None,
                        "can_retry":job=="DEFERRED",
                        "can_cancel":job in ("READY","DEFERRED","NEEDS_REVIEW"),
                        "last_admin_action":event,
                        "source":source,"release":release,
                       "received_at":received,"status":status,
                       "can_resolve":status=="NEEDS REVIEW" and not dispatch and not job,
                       "can_delete":status in ("NEEDS REVIEW","RECEIVED","IDENTIFYING") and not dispatch and not job,
                       "season":season,"episode":episode,
                       "series_title":title,"message":error or "", "activity_detail":explanation,
                       "staged":bool(stage and Path(stage).is_file())})
    searches=db.execute("""SELECT id,subject_key,payload_json,state,attempts,
        available_at,lease_until,last_error
        FROM daemon_jobs WHERE kind='series_gap_search' ORDER BY id DESC""").fetchall()
    for jid,key,payload,state,attempts,retry_at,lease_until,error in searches:
        request=json.loads(payload)
        event=events.get(jid)
        canceled=state=="BLOCKED" and event is not None and event["action"]=="cancel"
        job_status={"READY":"QUEUED","LEASED":"RUNNING","DONE":"COMPLETED",
                    "DEFERRED":"WAITING FOR SEARCH","BLOCKED":"BLOCKED",
                    "NEEDS_REVIEW":"NEEDS REVIEW"}.get(state,state)
        if canceled:
            job_status="CANCELED"
        explanation=("Canceled by an administrator. No torrent or media was deleted."
                     if canceled else error or ("Search job: "+job_status.lower()))
        result.append({"id":"search-"+str(jid),"job_id":jid,"job_state":state,
                        "attempts":attempts,"next_retry_at":retry_at if state=="DEFERRED" else None,
                        "lease_until":lease_until if state=="LEASED" else None,
                        "last_error":error or None,"last_admin_action":event,
                        "can_retry":state=="DEFERRED",
                        "can_cancel":state in ("READY","DEFERRED","NEEDS_REVIEW"),
                        "activity_detail":explanation,"source":request["origin"],
                       "release":request["title"]+" (one-time search)",
                       "received_at":0,"status":job_status,"season":request["season"],
                       "episode":None,"series_title":request["title"],
                       "message":error or "","staged":False})
    return _page(result,page,size)
