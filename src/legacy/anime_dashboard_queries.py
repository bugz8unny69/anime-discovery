"""Dashboard queries: staged Anime-Trial library and live acquisition jobs.

Series visibility comes from successful staging records, not from merely
recognizing a title in an incoming release. Pagination is applied after
verifying staged files still exist on disk.
"""
from pathlib import Path
import json

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
    for nid,source,release,received,nstatus,season,episode,dispatch,job,error,stage,title in rows:
        if job=="DONE" and dispatch=="DONE":
            status="COMPLETED"
        elif job=="LEASED":
            status="RUNNING"
        elif job=="READY":
            status="QUEUED"
        elif job=="DEFERRED":
            status="WAITING FOR DOWNLOAD"
        elif job=="BLOCKED":
            status="BLOCKED"
        elif nstatus=="NEEDS_REVIEW" or job=="NEEDS_REVIEW" or dispatch=="NEEDS_REVIEW":
            status="NEEDS REVIEW"
        elif job=="DONE":
            status="COMPLETED"
        elif dispatch=="CLAIMED":
            status="QUEUED"
        else:
            status="RECEIVED"
        # An unmatched intake record is not an acquisition job. Make that
        # distinction visible instead of suggesting an idle worker.
        if status in ("RECEIVED","NEEDS REVIEW"):
            explanation=("Waiting for episode identity: no acquisition job was created. "
                         "Recognize the title or approve notification #"+str(nid)+" with TVDB/AniDB IDs and episode.")
        elif status=="QUEUED":
            explanation="Acquisition job queued; waiting for a worker."
        elif status=="RUNNING":
            explanation="Acquisition worker has leased this job."
        elif status=="COMPLETED":
            explanation="Acquisition job completed."
        else:
            explanation=error or ("Current job state: "+status.lower())
        result.append({"id":nid,"source":source,"release":release,
                       "received_at":received,"status":status,
                       "season":season,"episode":episode,
                       "series_title":title,"message":error or "", "activity_detail":explanation,
                       "staged":bool(stage and Path(stage).is_file())})
    searches=db.execute("""SELECT id,subject_key,payload_json,state,last_error
        FROM daemon_jobs WHERE kind='series_gap_search' ORDER BY id DESC""").fetchall()
    for jid,key,payload,state,error in searches:
        request=json.loads(payload)
        job_status={"READY":"QUEUED","LEASED":"RUNNING","DONE":"COMPLETED",
                    "DEFERRED":"WAITING FOR SEARCH","BLOCKED":"BLOCKED",
                    "NEEDS_REVIEW":"NEEDS REVIEW"}.get(state,state)
        result.append({"id":"search-"+str(jid),"source":request["origin"],
                       "release":request["title"]+" (one-time search)",
                       "received_at":0,"status":job_status,"season":request["season"],
                       "episode":None,"series_title":request["title"],
                       "message":error or "","staged":False})
    return _page(result,page,size)
