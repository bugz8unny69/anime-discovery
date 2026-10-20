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
from anime_identity_crosscheck_v3 import explicit_anidb_ids,classify_tvdb
from anime_identity_mapping_v4 import download as download_anime_lists, resolve_episode as resolve_anime_lists_episode

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
    db.execute("""CREATE TABLE IF NOT EXISTS verified_anidb_episode_ids (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        anidb_id INTEGER NOT NULL,
        anidb_episode_number INTEGER NOT NULL,
        anidb_episode_id INTEGER NOT NULL,
        source TEXT NOT NULL
    )""")

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


def ensure_anime_lists(path, *, now=None, downloader=None):
    """Refresh the Anime-Lists mapping cache daily, validating before publish."""
    import xml.etree.ElementTree as ET
    now=int(time.time() if now is None else now)
    path=Path(path)
    if path.is_file() and now-int(path.stat().st_mtime)<86400:
        data=path.read_bytes()
    else:
        data=(downloader or download_anime_lists)()
        if not isinstance(data,bytes) or not data or len(data)>16*1024*1024:
            raise ValueError("Anime-Lists cache invalid or oversized")
        if ET.fromstring(data).tag!="anime-list":
            raise ValueError("Unexpected Anime-Lists root")
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    if ET.fromstring(data).tag!="anime-list":
        raise ValueError("Unexpected Anime-Lists root")
    return data


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
        names=row.get("candidate_titles")
        if not isinstance(names,list):
            names=[row.get("name") or ""] + (row.get("aliases") or [])
        names=[n[:180] for n in names[:16] if isinstance(n,str) and norm(n)]
        pairs=[(round(100*SequenceMatcher(None,norm(query),norm(title),autojunk=False).ratio()),
                query[:180],title)
               for query in aliases[:5] if isinstance(query,str) and norm(query)
               for title in names]
        score,query,title=max(pairs,key=lambda p:p[0]) if pairs else (0,"","")
        reason=("NO_USABLE_CANDIDATE_TITLES" if not names else
                "NO_USABLE_RELEASE_TITLES" if not pairs else
                "TITLE_SCORE_PASSED" if score>=threshold else "BELOW_TITLE_THRESHOLD")
        rows.append({"tvdb_id":str(row["tvdb_id"]),"name":str(row.get("name") or "")[:180],
                     "candidate_titles":names,"best_query":query,
                     "best_candidate_title":title,"score_pct":score,
                     "threshold_pct":threshold,"passed":bool(pairs) and score>=threshold,
                     "reason":reason})
    return rows

def investigate(name,settings,secrets,catalog,*,search=tvdb_candidates,login=tvdb_token,fetch=request_json,mapping_xml=None,anidb_resolve=None):
    aliases,episode=release_title(name)
    threshold=settings.get("identity",{}).get("match_threshold_pct",90)
    report={"title_queries":aliases[:5],"threshold_pct":threshold,
            "episode_candidate":episode,"anidb_candidates":[],
            "tvdb_candidates":[],"tvdb_results_count":0,"candidate_scores":[],
            "matching_pairs":[],"crossref_diagnostics":[],"episode_mapping":None,"workflow":[],
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
    if not rows:
        report["issues"].append("NO_ANIDB_EXACT_TITLE_MATCH")
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
    if not candidates:
        report["issues"].append("NO_TVDB_SEARCH_RESULTS")
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
        provider_ids=set(explicit_anidb_ids(detail))
        media_type,media_labels=classify_tvdb(detail)
        mapped={}
        if mapping_xml is not None and episode:
            for aid in sorted(aid_set):
                resolved=resolve_anime_lists_episode(mapping_xml,aid,tid,episode)
                if resolved is not None:
                    mapped[aid]=resolved
        match=aid_set.intersection(provider_ids)|set(mapped)
        report["crossref_diagnostics"].append({
            "tvdb_id":tid,"media_type":media_type,
            "media_labels":media_labels[:8],
            "explicit_anidb_ids":sorted(provider_ids)[:8],
            "anidb_candidate_ids":sorted(aid_set)[:10],
            "matching_anidb_ids":sorted(match),
            "anime_lists_anidb_ids":sorted(mapped),
            "reason":("EXPLICIT_ANIDB_MATCH" if match else
                      "TVDB_ANIDB_ID_CONFLICT" if provider_ids else
                      "TVDB_ANIDB_REMOTE_ID_MISSING")})
        if media_type in ("LIVE_ACTION","CONFLICTING_MEDIA_TYPE"):
            report["crossref_diagnostics"][-1]["reason"]="REJECTED_UNSUITABLE_TVDB_MEDIA_TYPE"
            continue
        for aid in sorted(match):
            report["matching_pairs"].append({"tvdb_id":tid,"anidb_id":aid,
               **({"episode_rule":mapped[aid]} if aid in mapped else {})})
    report["workflow"].append({"step":"Explicit TVDB-to-AniDB cross-reference",
                                "matching_pairs":len(report["matching_pairs"]),
                                "records_inspected":len(report["crossref_diagnostics"])})
    if not report["matching_pairs"]:
        report["issues"].append("NO_EXPLICIT_TVDB_ANIDB_CROSSREF")
    elif len(report["matching_pairs"])>1:
        report["issues"].append("MULTIPLE_TVDB_ANIDB_CROSSREFS")
    if len(report["matching_pairs"])==1 and episode and not report["issues"]:
        pair=report["matching_pairs"][0]
        tid=pair["tvdb_id"]
        rule=pair.get("episode_rule")
        report["episode_mapping"]=rule
        season=rule["tvdb_season"] if rule else 1
        mapped_ep=rule["tvdb_episode"] if rule else episode
        mapping=settings.get("identity",{}).get("episode_map",{}).get(
            tid+":"+str(season)+":"+str(mapped_ep))
        episode_id=(mapping.get("anidb_episode_id")
             if isinstance(mapping,dict) and mapping.get("verified") is True
             and type(mapping.get("anidb_episode_id")) is int
             and mapping["anidb_episode_id"]>0 else None)
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
                        row.get("seasonNumber")==season and row.get("number")==mapped_ep)
            links=response.get("links") or {}
            if not isinstance(links,dict) or not links.get("next"):
                break
        else:
            raise ValueError("TVDB episode pagination exceeded")
        if len(seen)!=1 or type(seen[0].get("id")) is not int:
            report["issues"].append("TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED")
        else:
            tvdb_ep_id=seen[0]["id"]
            if episode_id is None and rule and anidb_resolve is not None:
                episode_id=anidb_resolve(int(pair["anidb_id"]),
                                          rule["anidb_episode_number"])
                if type(episode_id) is not int or episode_id<=0:
                    episode_id=None
            # Shoko is only involved after Keep, never during trial triage.
            if episode_id is not None:
                report["decision"]="AUTO_VERIFIED"
                report["approval"]={"tvdb_id":int(tid),
                                    "anidb_id":int(pair["anidb_id"]),
                                    "season":season,"episode":mapped_ep}
                report["verified_anidb_episode_id"]=episode_id
            else:
                report["issues"].append("VERIFIED_EPISODE_MAPPING_MISSING")
                report["workflow"].append({"step":"Verified episode map","passed":False})
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
                mapping_xml=ensure_anime_lists(
                    Path(settings["daemon"]["database_path"]).parent/"anime-lists.xml")
                aid_cfg=settings.get("anidb",{})
                direct=None
                if aid_cfg.get("http_api_url") and aid_cfg.get("client"):
                    from anime_anidb_episode_lookup import lookup_episode_id
                    direct=lambda aid,ep: lookup_episode_id(
                        aid,ep,endpoint=aid_cfg["http_api_url"],
                        client=aid_cfg["client"],clientver=aid_cfg["clientver"],
                        cache_dir=Path(settings["daemon"]["database_path"]).parent/"anidb-episode-cache")
                report=investigate(title,settings,secrets,catalog,
                                   mapping_xml=mapping_xml,anidb_resolve=direct)
            decision=report["decision"]
            if decision=="AUTO_VERIFIED":
                from anime_webhook_processing import approve
                approve(db,nid,report["approval"],source="verified_identity_mapping")
                rule=report.get("episode_mapping")
                if rule and type(report.get("verified_anidb_episode_id")) is int:
                    db.execute("""INSERT INTO verified_anidb_episode_ids
                        (notification_id,anidb_id,anidb_episode_number,anidb_episode_id,source)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(notification_id) DO UPDATE SET
                        anidb_id=excluded.anidb_id,
                        anidb_episode_number=excluded.anidb_episode_number,
                        anidb_episode_id=excluded.anidb_episode_id,
                        source=excluded.source""",
                        (nid,report["approval"]["anidb_id"],
                         rule["anidb_episode_number"],
                         report["verified_anidb_episode_id"],"AniDB"))
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
            LOG.info("identity candidate=%s",json.dumps({"notification":nid,**candidate},ensure_ascii=True)[:1800])
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
                     "crossref_diagnostics":report.get("crossref_diagnostics",[])[:5],
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
        LOG.info("identity finalized notification=%s attempt=%s persisted_decision=%s retry=%s",
                 nid,attempts,decision,retry)
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
