"""Unified-inbox background identity triage.

Network evidence is observational; only configured exact mappings can
authorize a download through the existing webhook approval gate.
"""
import gzip
from difflib import SequenceMatcher
import io
import json
import logging
import sqlite3
import time
import urllib.request
from pathlib import Path
from anime_flat_config import load_config
from anime_identification_probe import release_title,anidb_matches,tvdb_candidates,norm
from anime_identity_verify import TITLES_URL,TVDB_URL,tvdb_token,request_json
from anime_identity_crosscheck_v3 import explicit_anidb_ids

LOG=logging.getLogger(__name__)
MAX_TITLES=32*1024*1024

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS unified_identity_checks (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        checked_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_at INTEGER NOT NULL DEFAULT 0,
        decision TEXT NOT NULL,
        evidence_json TEXT NOT NULL)""")

def ensure_titles(path,*,now=None,downloader=None):
    """Use cached public AniDB titles; refresh at most daily."""
    now=int(time.time() if now is None else now)
    path=Path(path)
    if path.is_file() and now-int(path.stat().st_mtime)<86400:
        return path
    if downloader is None:
        def downloader():
            request=urllib.request.Request(TITLES_URL,headers={"User-Agent":"AnimeDiscovery/1.0"})
            with urllib.request.urlopen(request,timeout=25) as response:
                return response.read(MAX_TITLES+1)
    payload=downloader()
    if not isinstance(payload,bytes) or len(payload)>MAX_TITLES or not payload:
        raise ValueError("Invalid or oversized public AniDB catalog")
    # Validate the downloaded catalog before replacing a known-good cache.
    import xml.etree.ElementTree as ET
    content=(gzip.GzipFile(fileobj=io.BytesIO(payload)).read(MAX_TITLES*4+1)
             if payload.startswith(b"\x1f\x8b") else payload)
    if len(content)>MAX_TITLES*4:
        raise ValueError("Decompressed AniDB catalog too large")
    if ET.fromstring(content).tag!="animetitles":
        raise ValueError("Unexpected AniDB title catalog")
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    try:
        tmp.write_bytes(payload)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path

def candidate_score(aliases,names):
    """Highest normalized title similarity, recorded for review only."""
    normalized=[norm(x) for x in aliases if isinstance(x,str) and norm(x)]
    options=[norm(x) for x in names if isinstance(x,str) and norm(x)]
    if not normalized or not options:
        return 0
    return round(100*max(SequenceMatcher(None,a,b,autojunk=False).ratio()
                         for a in normalized for b in options))

def title_diagnostics(aliases,candidates,threshold):
    rows=[]
    for row in candidates:
        names=[row.get("name") or "",row.get("matched_query") or ""]
        # matched_query is a search input, not candidate evidence; never score it.
        names=names[:1]+[x for x in row.get("aliases",[]) if isinstance(x,str)]
        score=candidate_score(aliases,names)
        rows.append({"tvdb_id":str(row["tvdb_id"]),"name":str(row.get("name") or "")[:180],
                     "score_pct":score,"threshold_pct":threshold,
                     "passed":score>=threshold,
                     "reason":"TITLE_SCORE_PASSED" if score>=threshold else "BELOW_TITLE_THRESHOLD"})
    return rows

def investigate(name,settings,secrets,catalog,*,search=tvdb_candidates,login=tvdb_token,fetch=request_json):
    aliases,episode=release_title(name)
    threshold=settings.get("identity",{}).get("match_threshold_pct",90)
    report={"title_queries":aliases[:5],"threshold_pct":threshold,
            "episode_candidate":episode,"anidb_candidates":[],
            "tvdb_candidates":[],"tvdb_results_count":0,"candidate_scores":[],
            "matching_pairs":[],"workflow":[],
            "decision":"NEEDS_REVIEW","issues":[]}
    if episode is None or episode<1:
        report["issues"].append("EPISODE_NUMBER_UNRESOLVED")
    if not settings.get("anidb",{}).get("enabled",True):
        report["issues"].append("ANIDB_PUBLIC_SOURCE_DISABLED")
        return report
    rows,truncated=anidb_matches(catalog,aliases,limit=10)
    report["workflow"].append({"step":"AniDB public titles","returned":len(rows),
                                "mode":"exact normalized title","truncated":bool(truncated)})
    report["anidb_candidates"]=[r["anidb_id"] for r in rows]
    if truncated:
        report["issues"].append("AMBIGUOUS_ANIDB_TITLES")
    if not settings["tvdb"]["enabled"] or not secrets.get("tvdb_api_key"):
        report["issues"].append("TVDB_DISABLED_OR_KEY_MISSING")
        return report
    candidates,errors=search(aliases,secrets["tvdb_api_key"])
    report["tvdb_candidates"]=[str(c["tvdb_id"]) for c in candidates]
    report["tvdb_results_count"]=len(candidates)
    report["candidate_scores"]=title_diagnostics(aliases,candidates,threshold)
    report["workflow"].append({"step":"TVDB search","returned":len(candidates),
                                "threshold_pct":threshold})
    report["issues"].extend(errors)
    if errors:
        raise RuntimeError("TVDB search incomplete")
    if len(candidates)>10:
        report["issues"].append("AMBIGUOUS_TVDB_CANDIDATES")
        return report
    token=login(secrets["tvdb_api_key"])
    accepted={r["tvdb_id"] for r in report["candidate_scores"] if r["passed"]}
    report["workflow"].append({"step":"Title score filter","passed":len(accepted),
                                "rejected":len(candidates)-len(accepted)})
    if not accepted:
        report["issues"].append("ALL_TVDB_TITLES_BELOW_THRESHOLD")
        return report
    aid_set={str(x["anidb_id"]) for x in rows}
    for candidate in candidates[:10]:
        tid=str(candidate["tvdb_id"])
        if tid not in accepted:
            continue
        detail=fetch(TVDB_URL+"/series/"+str(int(tid))+"/extended",bearer=token).get("data") or {}
        if str(detail.get("id"))!=tid:
            raise ValueError("TVDB ID response mismatch")
        match=aid_set.intersection(explicit_anidb_ids(detail))
        for aid in sorted(match):
            report["matching_pairs"].append({"tvdb_id":tid,"anidb_id":aid})
    report["workflow"].append({"step":"Explicit TVDB-to-AniDB cross-reference",
                                "matching_pairs":len(report["matching_pairs"])})
    if len(report["matching_pairs"])==1 and episode and not report["issues"]:
        pair=report["matching_pairs"][0]
        tid=pair["tvdb_id"]
        mapping=settings.get("identity",{}).get("episode_map",{}).get(
            tid+":1:"+str(episode))
        if isinstance(mapping,dict) and mapping.get("verified") is True and type(
                mapping.get("anidb_episode_id")) is int and mapping["anidb_episode_id"]>0:
            # A locally reviewed, exact episode mapping is required. Also
            # independently confirm this aired TVDB episode actually exists.
            seen=[]
            for page in range(20):
                url=TVDB_URL+"/series/"+str(int(tid))+"/episodes/default?page="+str(page)
                response=fetch(url,bearer=token)
                contents=response.get("data") or {}
                episodes=(contents.get("episodes",[]) if isinstance(contents,dict)
                          else contents if isinstance(contents,list) else [])
                if not isinstance(episodes,list):
                    raise ValueError("Invalid TVDB episode response")
                seen.extend(row for row in episodes if isinstance(row,dict) and
                            row.get("seasonNumber")==1 and row.get("number")==episode)
                links=response.get("links") or {}
                if not isinstance(links,dict) or not links.get("next"):
                    break
            else:
                raise ValueError("TVDB episode pagination exceeded")
            if len(seen)==1 and isinstance(seen[0].get("id"),int):
                report["decision"]="AUTO_VERIFIED"
                report["approval"]={"tvdb_id":int(tid),
                                    "anidb_id":int(pair["anidb_id"]),
                                    "season":1,"episode":episode}
                report["verified_anidb_episode_id"]=mapping["anidb_episode_id"]
            else:
                report["issues"].append("TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED")
        else:
            report["issues"].append("VERIFIED_EPISODE_MAPPING_MISSING")
            report["workflow"].append({"step":"Verified episode map", "passed":False})
        if report["decision"]!="AUTO_VERIFIED":
            report["decision"]="SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED"
    else:
        report["issues"].append("EXACT_IDENTITY_NOT_VERIFIED")
    return report

def check_once(db,settings,secrets,*,now=None,probe=None,limit=1):
    now=int(time.time() if now is None else now)
    ensure_schema(db)
    # Historical unmatched records need the same evidence check, not an
    # immediate notification from the NTFY monitor.
    db.execute("""UPDATE notifications SET status='IDENTIFYING'
        WHERE status IN ('UNTRUSTED','RECEIVED') AND NOT EXISTS
        (SELECT 1 FROM episode_dispatch d WHERE d.notification_id=notifications.id)""")
    db.commit()
    selected=db.execute("""SELECT n.id,n.release_name,COALESCE(c.attempts,0)
        FROM notifications n LEFT JOIN unified_identity_checks c ON c.notification_id=n.id
        WHERE n.status='IDENTIFYING' AND (c.next_at IS NULL OR c.next_at<=?)
        ORDER BY n.id LIMIT ?""",(now,limit)).fetchall()
    done=0
    pending_retries=0
    for nid,title,attempts in selected:
        attempts+=1
        try:
            if probe:
                report=probe(title,settings,secrets)
            elif not settings.get("anidb",{}).get("enabled",True):
                report={"decision":"NEEDS_REVIEW","issues":["ANIDB_PUBLIC_SOURCE_DISABLED"]}
            else:
                catalog=ensure_titles(Path(settings["daemon"]["database_path"]).parent/"anidb-titles.xml.gz")
                report=investigate(title,settings,secrets,catalog)
            decision=report["decision"]
            if decision=="AUTO_VERIFIED":
                from anime_webhook_processing import approve
                approve(db,nid,report["approval"],source="verified_identity_mapping")
                # approve() atomically records proof and queues the job.
                db.execute("UPDATE notifications SET status='APPROVED' WHERE id=? AND status='IDENTIFYING'",(nid,))
            retry=False
        except Exception as exc:
            decision="LOOKUP_RETRY" if attempts<3 else "NEEDS_REVIEW"
            report={"decision":decision,"issues":["LOOKUP_"+type(exc).__name__]}
            retry=attempts<3
            pending_retries+=int(retry)
            LOG.warning("Identity triage retry notification=%s error_type=%s",nid,type(exc).__name__)
        LOG.info("identity notification=%s attempt=%s decision=%s threshold=%s anidb_matches=%s tvdb_candidates=%s issues=%s",
                 nid,attempts,decision,report.get("threshold_pct","n/a"),
                 len(report.get("anidb_candidates",[])),
                 report.get("tvdb_results_count","n/a"),
                 ",".join(report.get("issues",[])[:8]))
        for candidate in report.get("candidate_scores",[])[:10]:
            LOG.info("identity notification=%s tvdb_candidate=%s score=%s threshold=%s result=%s",
                     nid,candidate["tvdb_id"],candidate["score_pct"],
                     candidate["threshold_pct"],candidate["reason"])
        for step in report.get("workflow",[])[:12]:
            LOG.info("identity notification=%s step=%s details=%s",
                     nid,step.get("step"),json.dumps({k:v for k,v in step.items() if k!="step"},sort_keys=True))
        # Never expose API keys or release payloads in stored diagnostics.
        safe=json.dumps(report,sort_keys=True)
        if len(safe)>16000:
            compact={"decision":decision,"issues":report.get("issues",[])[:8],
                     "threshold_pct":report.get("threshold_pct"),
                     "tvdb_results_count":report.get("tvdb_results_count"),
                     "candidate_scores":report.get("candidate_scores",[])[:5],
                     "workflow":report.get("workflow",[])[:5]}
            safe=json.dumps(compact,sort_keys=True)
            if len(safe)>16000:
                safe=json.dumps({"decision":decision,"issues":["TRACE_TRUNCATED"]})

        with db:
            db.execute("""INSERT INTO unified_identity_checks
                (notification_id,checked_at,attempts,next_at,decision,evidence_json)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(notification_id) DO UPDATE SET
                checked_at=excluded.checked_at,attempts=excluded.attempts,
                next_at=excluded.next_at,decision=excluded.decision,
                evidence_json=excluded.evidence_json""",
                (nid,now,attempts,now+min(3600,60*2**attempts) if retry else 0,decision,safe))
            if not retry and decision!="AUTO_VERIFIED":
                db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=? AND status='IDENTIFYING'",(nid,))
        done+=1
    return {"processed":done,"pending_retries":pending_retries}

def main():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    while True:
        try:
            cfg=load_config()
            with sqlite3.connect(cfg["settings"]["daemon"]["database_path"],timeout=10) as db:
                db.execute("PRAGMA busy_timeout=10000")
                check_once(db,cfg["settings"],cfg["secrets"])
        except Exception as exc:
            LOG.warning("Identity triage failed error_type=%s",type(exc).__name__)
        time.sleep(60)

if __name__=="__main__":
    main()
