"""Dashboard queries: staged Anime-Trial library and live acquisition jobs.

Series visibility comes from successful staging records, not from merely
recognizing a title in an incoming release. Pagination is applied after
verifying staged files still exist on disk.
"""
from pathlib import Path
import json
from anime_job_management import latest_events, has_staged_media
from anime_review_messages import describe_review

PAGE_SIZES=(20,50,100)
JOB_STATUSES=("RECEIVED","IDENTIFYING","NEEDS REVIEW","QUEUED","RUNNING",
              "DOWNLOADING","WAITING FOR DOWNLOAD","WAITING FOR SEARCH",
              "COMPLETED","BLOCKED","CANCELED")


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
        if sid not in grouped:
            grouped[sid]={"id":sid,"title":title,"tvdb_id":tvdb,
                          "status":status,"staged_episodes":0,"missing_staged_episodes":0,"latest_episode":""}
        if not path or not Path(path).is_file():
            grouped[sid]["missing_staged_episodes"]+=1
            continue
        grouped[sid]["staged_episodes"]+=1
        grouped[sid]["latest_episode"]="S%02dE%02d"%(season,episode)
    if grouped and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sonarr_reconciliation'").fetchone():
        for sid,result in db.execute("""SELECT series_id,result FROM sonarr_reconciliation
            WHERE result IN ('ALREADY_MANAGED','PARTIALLY_MANAGED')"""):
            if sid in grouped:
                grouped[sid]["sonarr_reconciliation"]=result
    return _page(list(grouped.values()),page,size)


def all_jobs(db, *,page=1,size=20,status="ALL"):
    """One activity entry per incoming release including unmatched webhook events."""
    page,size=pagination(page,size)
    if status!="ALL" and status not in JOB_STATUSES:
        raise ValueError("Invalid job status filter")
    events=latest_events(db)
    cleanup_reviews={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daemon_job_cleanup_review'").fetchone():
        cleanup_reviews={jid:state for jid,state in db.execute(
            "SELECT job_id,status FROM daemon_job_cleanup_review")}
    identity_checks={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_identity_checks'").fetchone():
        for nid,decision,document in db.execute(
                "SELECT notification_id,decision,evidence_json FROM unified_identity_checks"):
            try:
                evidence=json.loads(document)
                codes=evidence.get("issues") or []
                safe_codes=[x for x in codes if isinstance(x,str) and
                    len(x)<=100 and all(c.isalnum() or c=="_" for c in x)]
                batch=evidence.get("batch_authorization") or {}
                scope=(evidence.get("release_scope_hint") or {}).get("kind")
                batch_action=(batch.get("action","") if isinstance(batch,dict) else "")
                if not isinstance(batch_action,str):
                    batch_action=""
                is_pack=(scope=="season_pack" or
                         (isinstance(batch,dict) and batch.get("decision")=="BLOCKED"))
                identity_checks[nid]=(decision,safe_codes[:3],is_pack,
                                      batch_action[:240])
            except (TypeError,ValueError,AttributeError):
                identity_checks[nid]=("UNKNOWN",[],False,"")
    batch_stages={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_batch_executions'").fetchone():
        batch_stages=dict(db.execute("SELECT notification_id,state FROM anime_batch_executions"))
    rows=db.execute("""SELECT n.id,n.source,n.release_name,n.received_at,n.status,
        d.season,d.episode,d.state,
        j.id,j.state,j.attempts,j.available_at,j.lease_until,j.last_error,r.staged_path,
        COALESCE(s.title,'')
        FROM notifications n
        LEFT JOIN episode_dispatch d ON d.notification_id=n.id
        LEFT JOIN series s ON s.id=d.series_id
        LEFT JOIN daemon_jobs j ON j.kind IN
             ('claimed_acquisition','verified_batch_acquisition')
             AND j.subject_key=CAST(n.id AS TEXT)
        LEFT JOIN torrent_recovery_records r ON r.notification_id=n.id
        ORDER BY n.id DESC""").fetchall()
    result=[]
    for nid,source,release,received,nstatus,season,episode,dispatch,job_id,job,attempts,retry_at,lease_until,error,stage,title in rows:
        batch_stage=batch_stages.get(nid)
        batch_active=bool(batch_stage in ("PROBE","UNLOCKED") and job in ("DEFERRED","LEASED","READY"))
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
            status="DOWNLOADING" if batch_active else "WAITING FOR DOWNLOAD"
        elif job=="BLOCKED":
            status="BLOCKED"
        elif job=="NEEDS_REVIEW" or dispatch=="NEEDS_REVIEW":
            status="NEEDS REVIEW"
        elif job=="DONE" or (dispatch=="DONE" and not job):
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
        if status in ("RECEIVED","NEEDS REVIEW") and not job:
            _check=identity_checks.get(nid,("",[],False,""))
            if _check[2]:
                explanation=("Season-pack verification requires review; no batch download was authorized. "
                             +(_check[3] or "Review its season hint, recognized title and independent provider evidence.")+
                             " Do not assign an arbitrary single episode to a season pack.")
            else:
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
        elif batch_active:
            explanation=("Downloading verified episodes; waiting for episode file completion. "
                         "Live qBittorrent progress is not available in this view; "
                         "this status does not confirm that transfer speed is nonzero.")
        elif status=="CANCELED":
            explanation="Canceled by administrator."
        else:
            explanation=error or ("Current job state: "+status.lower())
        if status=="NEEDS REVIEW" and job:
            explanation="Needs review. Check service logs for technical details."
        if status=="NEEDS REVIEW" and not job and error=="QBITTORRENT_SAVE_PATH_OUTSIDE_DOWNLOAD_ROOT":
            explanation=("qBittorrent's save_path is outside Anime Discovery's configured "
                         "download_root. Compare the exact torrent save_path with "
                         "settings.storage.download_root in the worker's filesystem namespace. "
                         "Correct the path configuration or the torrent save location; "
                         "do not disable the containment check or move verified files blindly.")
        if status in ("IDENTIFYING","NEEDS REVIEW") and not job and nid in identity_checks:
            decision,codes,_is_pack,_action=identity_checks[nid]
            explanation+=" Latest identity check: "+str(decision)[:80]
            if decision=="BATCH_VERIFIED":
                codes=[x for x in codes if x not in (
                    "BATCH_FILE_MANIFEST_REQUIRED",
                    "EPISODE_NUMBER_UNRESOLVED",
                    "EXACT_IDENTITY_NOT_VERIFIED")]
            if codes:
                if any(code.startswith("LOOKUP_") for code in codes):
                    explanation=describe_review(next(code for code in codes if code.startswith("LOOKUP_")))
                elif status=="NEEDS REVIEW":
                    explanation=describe_review(codes[0])
                else:
                    explanation+="; "+", ".join(codes)
        result.append({"id":nid,"job_id":job_id,"job_state":job,"attempts":attempts,
                        "next_retry_at":retry_at if job=="DEFERRED" else None,
                        "lease_until":lease_until if job=="LEASED" else None,
                        "last_error":error or None,
                        "batch_download_active":batch_active,
                        "batch_stage":batch_stage,
                        "can_retry":job=="NEEDS_REVIEW",
                        "can_cancel":job=="NEEDS_REVIEW" and not bool(stage and Path(stage).is_file()) and not has_staged_media(db,"verified_batch_acquisition" if nstatus=="APPROVED_BATCH" else "claimed_acquisition",str(nid)),
                        "last_admin_action":event,
                        "source":source,"release":release,
                       "received_at":received,"status":status,
                       "can_resolve":status=="NEEDS REVIEW" and not dispatch and not job,
                       "can_recheck":nstatus=="NEEDS_REVIEW" and not dispatch and not job,
                       "can_delete":status in ("NEEDS REVIEW","RECEIVED","IDENTIFYING") and not dispatch and not job,
                       "season":season,"episode":episode,
                       "series_title":title,"message":error or "", "activity_detail":explanation,
                       "staged":bool(stage and Path(stage).is_file())})
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='daemon_job_archived_subjects'").fetchone():
        history=db.execute("""SELECT a.job_id,n.id,n.source,n.release_name,n.received_at,
            j.attempts,j.last_error,j.kind
            FROM daemon_job_archived_subjects a
            JOIN daemon_jobs j ON j.id=a.job_id
            JOIN notifications n ON a.original_subject_key=CAST(n.id AS TEXT)
            WHERE j.state='BLOCKED'
              AND a.kind IN ('verified_batch_acquisition','claimed_acquisition')
            ORDER BY a.job_id DESC""").fetchall()
        for jid,nid,source,release,received,attempts,old_error,kind in history:
            cleanup_status=cleanup_reviews.get(jid,"NOT_VERIFIED")
            cleanup_message=("Canceled; resource cleanup needs review."
                             if cleanup_status=="REVIEW_REQUIRED"
                             else "Canceled; resource cleanup has not been verified.")
            result.append({"id":nid,"job_id":jid,"job_state":"BLOCKED",
                "attempts":attempts,"last_error":old_error,
                "last_admin_action":events.get(jid),
                "source":source,"release":release,"received_at":received,
                "status":"CANCELED","message":"","activity_detail":cleanup_message,
                "cleanup_status":cleanup_status,
                "can_retry":False,"can_cancel":False,"can_resolve":False,
                "can_recheck":False,"can_delete":False,"season":None,"episode":None,
                "series_title":"","staged":False})
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
        explanation=("Canceled by administrator."
                     if canceled else error or ("Search job: "+job_status.lower()))
        result.append({"id":"search-"+str(jid),"job_id":jid,"job_state":state,
                        "attempts":attempts,"next_retry_at":retry_at if state=="DEFERRED" else None,
                        "lease_until":lease_until if state=="LEASED" else None,
                        "last_error":error or None,"last_admin_action":event,
                        "can_retry":state=="NEEDS_REVIEW",
                        "can_cancel":state=="NEEDS_REVIEW",
                        "activity_detail":explanation,"source":request["origin"],
                       "release":request["title"]+" (one-time search)",
                       "received_at":0,"status":job_status,"season":request["season"],
                       "episode":None,"series_title":request["title"],
                       "message":"","staged":False})
    return _page([item for item in result if status=="ALL" or item["status"]==status],page,size) | {"status_filter":status}
