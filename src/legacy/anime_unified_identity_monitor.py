"""Provider-backed identity resolution used by queued identity jobs.

Network evidence is observational; only configured exact mappings can
authorize a download through the existing webhook approval gate.
"""
import gzip
from difflib import SequenceMatcher
import io
import json
import logging
from anime_diagnostics import event, Span, configure_logging
import sqlite3
import time
from anime_config_wakeup import wait_for_change
import urllib.request
import xml.etree.ElementTree as ET
from anime_xml_response_diagnostics import InvalidXMLResponse,log_bad_xml
from pathlib import Path
from anime_flat_config import load_config
from anime_identification_probe import release_title,anidb_matches,tvdb_candidates,norm,candidate_titles
from anime_batch_selection import release_scope_hint
from anime_identity_verify import TITLES_URL,TVDB_URL,tvdb_token,request_json
from anime_identity_crosscheck_v3 import explicit_anidb_ids,classify_tvdb
from anime_identity_mapping_v4 import download as download_anime_lists, resolve_episode as resolve_anime_lists_episode, resolve_tvdb_episode
from anime_tvdb_throttle import tvdb_scope, TVDBDeferred
from anime_season_candidate_discovery import season_candidates

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

class MetadataUnavailable(Exception):
    """Upstream/cached metadata is unusable; retry without a review alert."""
    def __init__(self, source):
        self.source=source
        super().__init__("Metadata unavailable: "+source)


def _validate_titles(payload):
    import xml.etree.ElementTree as ET
    if not isinstance(payload,bytes) or not payload or len(payload)>MAX_TITLES:
        raise ValueError("Invalid or oversized AniDB titles")
    content=(gzip.GzipFile(fileobj=io.BytesIO(payload)).read(MAX_TITLES*4+1)
             if payload.startswith(b"\x1f\x8b") else payload)
    if len(content)>MAX_TITLES*4:
        raise ValueError("AniDB titles decompressed past size limit")
    if ET.fromstring(content).tag!="animetitles":
        raise ValueError("Wrong AniDB titles root")
    return payload


def _validate_mapping(data):
    import xml.etree.ElementTree as ET
    if not isinstance(data,bytes) or not data or len(data)>16*1024*1024:
        raise ValueError("Invalid Anime-Lists payload")
    if ET.fromstring(data).tag!="anime-list":
        raise ValueError("Wrong Anime-Lists root")
    return data


def _validated_cache(path,validator,source):
    if not path.is_file():
        return None
    try:
        raw=path.read_bytes()
        return validator(raw)
    except Exception as failure:
        # Do not reuse truncated, malformed, or otherwise untrusted cache data.
        log_bad_xml(source,locals().get("raw",b""),reason="CACHE_"+type(failure).__name__)
        return None


def _refresh_cache(path,*,now,downloader,validator,source):
    """Cache validated XML atomically, retaining last-good on HTTP/XML errors."""
    path=Path(path)
    cached=_validated_cache(path,validator,source)
    if cached is not None and 0<=now-int(path.stat().st_mtime)<86400:
        return cached
    downloaded_raw=None
    try:
        downloaded_raw=downloader()
        downloaded=validator(downloaded_raw)
    except Exception as exc:
        if downloaded_raw is not None:
            log_bad_xml(source,downloaded_raw,reason=type(exc).__name__)
        if cached is not None:
            LOG.warning("Metadata refresh deferred source=%s error_type=%s using_last_good=true",
                        source,type(exc).__name__)
            return cached
        LOG.warning("Metadata unavailable source=%s error_type=%s",source,type(exc).__name__)
        raise MetadataUnavailable(source) from None
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    try:
        tmp.write_bytes(downloaded)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return downloaded


def ensure_titles(path,*,now=None,downloader=None):
    """Return validated AniDB title cache path; never accept malformed XML."""
    now=int(time.time() if now is None else now)
    if downloader is None:
        def downloader():
            request=urllib.request.Request(TITLES_URL,headers={"User-Agent":"AnimeDiscovery/1.0"})
            with urllib.request.urlopen(request,timeout=25) as response:
                return response.read(MAX_TITLES+1)
    _refresh_cache(path,now=now,downloader=downloader,
                   validator=_validate_titles,source="ANIDB_TITLES")
    return Path(path)


def ensure_anime_lists(path,*,now=None,downloader=None):
    """Return a validated Anime-Lists XML mapping from the local cache."""
    now=int(time.time() if now is None else now)
    return _refresh_cache(path,now=now,downloader=downloader or download_anime_lists,
                          validator=_validate_mapping,source="ANIME_LISTS")


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

def _anidb_family_title(aliases,titles):
    """Advisory family-title corroboration; never approval on its own."""
    terms=[norm(a) for a in aliases if isinstance(a,str) and len(norm(a))>=6]
    names=[norm(t) for t in titles if isinstance(t,str)]
    return any(n.startswith(term) or term.startswith(n)
               for term in terms for n in names if n and len(n)>=6)

def investigate(name,settings,secrets,catalog,*,search=tvdb_candidates,login=tvdb_token,fetch=request_json,mapping_xml=None,anidb_resolve=None,trusted_season=None):
    aliases,episode=release_title(name)
    threshold=settings.get("identity",{}).get("match_threshold_pct",90)
    report={"title_queries":aliases[:5],"threshold_pct":threshold,
            "episode_candidate":episode,"anidb_candidates":[],
            "tvdb_candidates":[],"tvdb_results_count":0,"candidate_scores":[],
            "matching_pairs":[],"crossref_diagnostics":[],"season_mapping_candidates":[],
             "episode_mapping":None,"workflow":[],
            "decision":"NEEDS_REVIEW","issues":[]}
    # Hints improve Needs Review diagnostics only: never approve from a
    # torrent name, especially a batch without a verified file manifest.
    hint=release_scope_hint(name)
    report["release_scope_hint"]=hint
    if hint["kind"] == "season_pack":
        report["issues"].append("BATCH_FILE_MANIFEST_REQUIRED")
    elif hint["kind"] == "special":
        report["issues"].append("SEASON_ZERO_SPECIAL_OUTSIDE_TRIAL_SCOPE")
    elif hint["kind"] == "ambiguous_season":
        report["issues"].append("MIXED_OR_AMBIGUOUS_SEASON_HINT")
    if episode is None or episode<1:
        report["issues"].append("EPISODE_NUMBER_UNRESOLVED")
    if not settings.get("anidb",{}).get("enabled",True):
        report["issues"].append("ANIDB_PUBLIC_SOURCE_DISABLED")
        return report
    # A cached name is a discovery accelerator, never a verified episode.
    # Trust it only with exact normalized title, explicitly numbered season,
    # and still-current unique Anime-Lists season mapping. Subsequent TVDB
    # metadata, episode mapping and AniDB episode ID checks remain mandatory.
    known=None
    if trusted_season:
        from anime_verified_season_memory import proven_season_mapping
        if (aliases and norm(aliases[0])==norm(trusted_season.get("title",""))
                and hint.get("season_hint")==trusted_season.get("season")
                and hint.get("kind")=="single_episode"
                and proven_season_mapping(mapping_xml,
                    trusted_season["tvdb_id"],trusted_season["season"],
                    trusted_season["anidb_id"])):
            known=trusted_season
    if known:
        rows=[{"anidb_id":known["anidb_id"],
               "matched_titles":[known["title"]],"titles":[known["title"]]}]
        truncated=False
        report["workflow"].append({"step":"Verified season cache",
            "source":"independent_prior_verification",
            "tvdb_id":known["tvdb_id"],"anidb_id":known["anidb_id"],
            "season":known["season"],"provider_revalidation":True})
    else:
        try:
            rows,truncated=anidb_matches(catalog,aliases,limit=10)
        except ET.ParseError:
            log_bad_xml("ANIDB_TITLES_CACHE",Path(catalog).read_bytes(),
                        reason="ITERPARSE_FAILURE")
            raise InvalidXMLResponse("ANIDB_TITLES_CACHE","ITERPARSE_FAILURE") from None
    report["workflow"].append({"step":"AniDB public titles","returned":len(rows),
                                "mode":"exact normalized title","truncated":bool(truncated)})
    report["anidb_candidates"]=[{
        "anidb_id":str(r["anidb_id"]),
        "matched_titles":[t[:180] for t in r.get("matched_titles",[])[:5] if isinstance(t,str)],
        "titles":[t[:180] for t in r.get("titles",[])[:12] if isinstance(t,str)]
    } for r in rows]
    if not rows:
        report["issues"].append("NO_ANIDB_EXACT_TITLE_MATCH")
    if truncated:
        report["issues"].append("AMBIGUOUS_ANIDB_TITLES")
    if not settings["tvdb"]["enabled"] or not secrets.get("tvdb_api_key"):
        report["issues"].append("TVDB_DISABLED_OR_KEY_MISSING")
        return report
    # AniDB -> Anime-Lists -> targeted TVDB: avoid broad title searches when
    # exactly one TVDB series is cross-referenced by the title-matched AniDB IDs.
    targeted={}
    if mapping_xml is not None and rows and not truncated and not known:
        root=ET.fromstring(mapping_xml)
        if root.tag!="anime-list":
            raise ValueError("Invalid Anime-Lists cross-reference root")
        aids={str(r["anidb_id"]) for r in rows}
        tids={node.get("tvdbid") for node in root.findall("anime")
              if node.get("anidbid") in aids and (node.get("tvdbid") or "").isdecimal()
              and int(node.get("tvdbid"))>0}
        if len(tids)==1:
            tid=tids.pop()
            token=login(secrets["tvdb_api_key"])
            detail=fetch(TVDB_URL+"/series/"+tid+"/extended",bearer=token).get("data") or {}
            if str(detail.get("id"))!=tid:
                raise ValueError("TVDB ID response mismatch")
            names=candidate_titles(detail)
            if names:
                targeted[tid]=detail
                candidates=[{"tvdb_id":tid,"name":names[0],
                             "candidate_titles":names}]
                errors=[]
                report["workflow"].append({"step":"AniDB-first targeted TVDB discovery",
                    "tvdb_id":tid,"source":"cached Anime-Lists","passed":True})
    if not targeted:
        if known:
            candidates=[{"tvdb_id":str(known["tvdb_id"]),"name":known["title"]}]
            errors=[]
        else:
            candidates,errors=search(aliases,secrets["tvdb_api_key"])
        report["workflow"].append({"step":"TVDB discovery fallback",
            "reason":"NO_UNIQUE_LOCAL_CROSSREFERENCE_OR_TVDB_TITLES"})
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
    # Search results must pass the title threshold before being counted as
    # genuinely ambiguous. Low-scoring noise cannot suppress a valid match.
    accepted={r["tvdb_id"] for r in report["candidate_scores"] if r["passed"]}
    report["workflow"].append({"step":"Title score filter","passed":len(accepted),
                                "rejected":len(candidates)-len(accepted)})
    if not accepted:
        report["issues"].append("ALL_TVDB_TITLES_BELOW_THRESHOLD")
        return report
    if len(accepted)>10:
        report["issues"].append("AMBIGUOUS_TVDB_CANDIDATES")
        return report
    token=token if targeted else login(secrets["tvdb_api_key"])
    aid_set={str(x["anidb_id"]) for x in rows}
    # Anime-Lists independently corroborates series ID pairs even if TVDB
    # lacks an AniDB remote ID. Parse the trusted cached XML exactly once.
    verified_xml_pairs={}
    if mapping_xml is not None:
        root=ET.fromstring(mapping_xml)
        if root.tag!="anime-list":
            raise ValueError("Invalid Anime-Lists cross-reference root")
        for node in root.findall("anime"):
            aid=node.get("anidbid")
            if aid in aid_set:
                verified_xml_pairs.setdefault(aid,[]).append(node.get("tvdbid"))
    for candidate in candidates:
        tid=str(candidate["tvdb_id"])
        if tid not in accepted:
            continue
        detail=(targeted[tid] if tid in targeted else
                fetch(TVDB_URL+"/series/"+str(int(tid))+"/extended",bearer=token).get("data") or {})
        if str(detail.get("id"))!=tid:
            raise ValueError("TVDB ID response mismatch")
        provider_ids=set(explicit_anidb_ids(detail))
        media_type,media_labels=classify_tvdb(detail)
        if (media_type not in ("LIVE_ACTION","CONFLICTING_MEDIA_TYPE")
                and hint.get("kind")=="single_episode"
                and mapping_xml is not None and catalog is not None):
            discovered=season_candidates(mapping_xml,catalog,tid,
                                         hint.get("season_hint"),episode)
            # A sequel's AniDB title must remain present in the official
            # catalog and independently resemble the parsed release family.
            # The TVDB title has already passed its independent threshold.
            for item in discovered:
                item["title_family_corrob"]=(item["title_index_present"]
                    and _anidb_family_title(aliases,item["titles"]))
            report["season_mapping_candidates"].extend(discovered)
            report["workflow"].append({"step":"Season-compatible Anime-Lists candidates",
                "tvdb_id":tid,"release_season":hint.get("season_hint"),
                "returned":len(discovered),"approval_authority":False})
        mapped={}
        if mapping_xml is not None and episode:
            for aid in sorted(aid_set):
                try:
                    resolved=(resolve_tvdb_episode(mapping_xml,aid,tid,
                        hint.get('season_hint'),episode)
                        if hint.get('kind')=='single_episode' else
                        resolve_anime_lists_episode(mapping_xml,aid,tid,episode))
                except ET.ParseError:
                    log_bad_xml("ANIME_LISTS_MAPPING",mapping_xml,
                                reason="MAPPING_PARSE_FAILURE")
                    raise InvalidXMLResponse("ANIME_LISTS_MAPPING",
                                              "MAPPING_PARSE_FAILURE") from None
                if resolved is not None:
                    mapped[aid]=resolved
        xml_pairs={aid for aid in aid_set
                   if verified_xml_pairs.get(aid)==[tid]}
        match=aid_set.intersection(provider_ids)|set(mapped)|xml_pairs
        report["crossref_diagnostics"].append({
            "tvdb_id":tid,"media_type":media_type,
            "media_labels":media_labels[:8],
            "explicit_anidb_ids":sorted(provider_ids)[:8],
            "anidb_candidate_ids":sorted(aid_set)[:10],
            "matching_anidb_ids":sorted(match),
            "anime_lists_anidb_ids":sorted(set(mapped)|xml_pairs),
            "reason":("EXPLICIT_ANIDB_MATCH" if match else
                      "TVDB_ANIDB_ID_CONFLICT" if provider_ids else
                      "TVDB_ANIDB_REMOTE_ID_MISSING")})
        if media_type in ("LIVE_ACTION","CONFLICTING_MEDIA_TYPE"):
            report["crossref_diagnostics"][-1]["reason"]="REJECTED_UNSUITABLE_TVDB_MEDIA_TYPE"
            continue
        for aid in sorted(match):
            report["matching_pairs"].append({"tvdb_id":tid,"anidb_id":aid,
               **({"episode_rule":mapped[aid]} if aid in mapped else {})})
    # Prefer a uniquely season-compatible, title-corroborated AniDB sequel
    # over an original-series cross-reference. Never infer a relationship from
    # the release season alone; the cached XML must resolve the exact episode.
    if hint.get("kind")=="single_episode" and report["season_mapping_candidates"]:
        acceptable={(item["tvdb_id"],item["anidb_id"]):item
                    for item in report["season_mapping_candidates"]
                    if item.get("title_family_corrob")}
        if len(acceptable)==1:
            key,item=next(iter(acceptable.items()))
            report["matching_pairs"]=[{"tvdb_id":key[0],"anidb_id":key[1],
                                       "episode_rule":item["episode_rule"]}]
            report["workflow"].append({"step":"Season-specific AniDB selection",
                "tvdb_id":key[0],"anidb_id":key[1],
                "source":"Anime-Lists episode rule + AniDB title family",
                "unique":True})
        elif len(acceptable)>1:
            report["issues"].append("AMBIGUOUS_SEASON_SPECIFIC_ANIDB")
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
        if rule is None:
            # A TVDB/AniDB series link does not establish an episode's season.
            # Never manufacture Season 1 or assume episode numbering matches.
            report["issues"].append("SEASON_EPISODE_MAPPING_UNVERIFIED")
            report["workflow"].append({"step":"Provider season agreement",
                "release_season":hint.get("season_hint"),
                "mapped_season":None,"passed":None,
                "reason":"NO_VERIFIED_ANIME_LISTS_EPISODE_RULE"})
            return report
        season=rule["tvdb_season"]
        mapped_ep=rule["tvdb_episode"]
        if (hint.get("kind")=="single_episode"
                and hint.get("season_hint")!=season):
            # Never assign a TVDB Season 2 release to Season 1 merely
            # because its cleaned title matches Season 1's AniDB record.
            report["issues"].append("RELEASE_SEASON_PROVIDER_MISMATCH")
            report["workflow"].append({"step":"Provider season agreement",
                "release_season":hint.get("season_hint"),
                "mapped_season":season,"passed":False})
            return report
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
                report["episode_id_source"]=(
                    "reviewed_episode_map" if mapping else "AniDB HTTP catalog")
            else:
                report["issues"].append("VERIFIED_EPISODE_MAPPING_MISSING")
                report["workflow"].append({"step":"Verified episode map","passed":False})
        if report["decision"]!="AUTO_VERIFIED":
            report["decision"]="SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED"
    else:
        report["issues"].append("EXACT_IDENTITY_NOT_VERIFIED")
    return report

def check_once(db,settings,secrets,*,now=None,probe=None,limit=1,notification_id=None):
    now=int(time.time() if now is None else now)
    ensure_schema(db)
    # Historical unmatched records need the same evidence check, not an
    # immediate notification from the NTFY monitor.
    if notification_id is None:
        db.execute("""UPDATE notifications SET status='IDENTIFYING'
        WHERE status IN ('UNTRUSTED','RECEIVED') AND NOT EXISTS
            (SELECT 1 FROM episode_dispatch d WHERE d.notification_id=notifications.id)""")
        db.commit()
    selected=db.execute("""SELECT n.id,n.release_name,COALESCE(c.attempts,0)
        FROM notifications n LEFT JOIN unified_identity_checks c ON c.notification_id=n.id
        WHERE n.status='IDENTIFYING' AND (c.next_at IS NULL OR c.next_at<=?)
          AND (? IS NULL OR n.id=?)
        ORDER BY n.id LIMIT ?""",(now,notification_id,notification_id,limit)).fetchall()
    done=0
    pending_retries=0
    for nid,title,attempts in selected:
        attempts+=1
        span=Span()
        retry_delay=None
        mapping_xml=None
        stage="IDENTITY_RESOLUTION" if probe else "ANIDB_TITLES"
        try:
            if probe:
                report=probe(title,settings,secrets)
            elif not settings.get("anidb",{}).get("enabled",True):
                report={"decision":"NEEDS_REVIEW","issues":["ANIDB_PUBLIC_SOURCE_DISABLED"]}
            else:
                from anime_verified_season_memory import known_for_release
                known=(known_for_release(db,title)
                       if settings.get("identity",{}).get("reuse_verified_cache",True)
                       else None)
                # No AniDB title-catalog search for a verified exact-series
                # cache hit. A cache hint still cannot approve an episode:
                # Anime-Lists and live TVDB/AniDB evidence remain required.
                if known is None:
                    catalog=ensure_titles(Path(settings["daemon"]["database_path"]).parent/"anidb-titles.xml.gz")
                else:
                    catalog=None
                stage="ANIME_LISTS"
                mapping_xml=ensure_anime_lists(
                    Path(settings["daemon"]["database_path"]).parent/"anime-lists.xml")
                if known:
                    from anime_verified_season_memory import proven_season_mapping
                    if not proven_season_mapping(mapping_xml,known["tvdb_id"],
                                                known["season"],known["anidb_id"]):
                        LOG.warning("event=VERIFIED_SEASON_CACHE_CONFLICT notification=%d "
                                    "reason=ANIME_LISTS_SEASON_MAPPING_CHANGED",nid)
                        # No silent fallback to a different AniDB identity.
                        known=None
                        catalog=ensure_titles(Path(settings["daemon"]["database_path"]).parent/"anidb-titles.xml.gz")
                aid_cfg=settings.get("anidb",{})
                direct=None
                if aid_cfg.get("client"):
                    from anime_anidb_episode_lookup import lookup_episode_id
                    direct=lambda aid,ep: lookup_episode_id(
                        aid,ep,client=aid_cfg["client"],
                        clientver=aid_cfg.get("clientver",1),
                        metadata_path=Path(settings["daemon"]["database_path"]).parent/"anime-metadata.db")
                stage="IDENTITY_RESOLUTION"
                with tvdb_scope(Path(settings["daemon"]["database_path"]).parent/"tvdb-throttle.db"):
                    report=investigate(title,settings,secrets,catalog,
                                       mapping_xml=mapping_xml,anidb_resolve=direct,
                                       trusted_season=known)
            decision=report["decision"]
            # The release name alone never authorizes season-pack acquisition.
            # Only this network-backed identity worker can promote a pending
            # Autobrr batch after a pinned alias and independent pair agree.
            if not probe and mapping_xml is not None and decision!="AUTO_VERIFIED":
                from anime_batch_verified_intake import authorize_verified_batch
                if authorize_verified_batch(db,nid,report,settings,mapping_xml):
                    decision="BATCH_VERIFIED"
                    report["decision"]=decision
            if decision=="AUTO_VERIFIED":
                # A valid independent identity remains reusable even if
                # acquisition later declines the episode (e.g. E1001 outside
                # the currently verified trial window). Identity != download.
                if mapping_xml is not None:
                    from anime_verified_season_memory import remember_from_report
                    try:
                        remember_from_report(db,title,report,mapping_xml,
                                             approved=report["approval"])
                    except ValueError as exc:
                        LOG.warning("event=VERIFIED_SEASON_CACHE_REVIEW notification=%d "
                                    "reason=%s",nid,type(exc).__name__)
                from anime_webhook_processing import approve
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
                         report["verified_anidb_episode_id"],
                         report.get("episode_id_source","verified_mapping")))
                # Save the exact AniDB ID first: if this write fails, do not
                # authorize a download without retained post-Keep provenance.
                db.commit()
                from anime_trial_policy import eligibility
                approved = report["approval"]
                policy = eligibility(db,tvdb_id=approved["tvdb_id"],
                                     anidb_id=approved["anidb_id"],
                                     season=approved["season"],episode=approved["episode"])
                if policy["eligible"]:
                    approve(db,nid,approved,source="verified_identity_mapping")
                    # approve() atomically records proof and queues the job.
                    db.execute("UPDATE notifications SET status='APPROVED' WHERE id=? AND status='IDENTIFYING'",(nid,))
                else:
                    # The verified identity is sound; only this incoming
                    # episode falls outside the configured evaluation range.
                    # This is a normal terminal outcome, never a lookup error.
                    search_titles=report.get("title_queries") or []
                    alias=next((name for name in search_titles
                                if isinstance(name,str) and name.strip() and len(name)<=200),None)
                    report["episode_range"]={"season":approved["season"],
                        "episode":approved["episode"],"start":policy["window"]["start"],
                        "end":policy["window"]["end"]}
                    if alias and settings.get("prowlarr",{}).get("enabled",False):
                        from anime_shared_discovery import schedule
                        schedule(db,title=alias,tvdb_id=approved["tvdb_id"],
                                 anidb_id=approved["anidb_id"],season=approved["season"],
                                 up_to=policy["window"]["end"],origin="autobrr")
                        report["issues"]=["EPISODE_EXCLUDED_BACKFILL_QUEUED"]
                    else:
                        report["issues"]=["EPISODE_EXCLUDED_BACKFILL_UNAVAILABLE"]
                    decision="EPISODE_EXCLUDED"
                    report["decision"]=decision
                    db.execute("""UPDATE notifications SET status='EXCLUDED_TRIAL_WINDOW'
                        WHERE id=? AND status='IDENTIFYING'""",(nid,))
            retry=False
        except Exception as exc:
            import xml.etree.ElementTree as ET
            from anime_anidb_episode_lookup import AniDBLookupDeferred
            if isinstance(exc,(MetadataUnavailable,InvalidXMLResponse,ET.ParseError,gzip.BadGzipFile,EOFError)):
                # An unavailable public metadata feed is not a user-review
                # decision, regardless of how often the provider has failed.
                source=exc.source if isinstance(exc,(MetadataUnavailable,InvalidXMLResponse)) else stage
                decision="LOOKUP_RETRY"
                report={"decision":decision,"issues":["METADATA_UNAVAILABLE_"+source]}
                retry=True
                retry_delay=min(3600,60*2**min(attempts,6))
                pending_retries+=1
                LOG.warning("Identity metadata retry notification=%s source=%s error_type=%s",
                            nid,source,type(exc).__name__)
            elif isinstance(exc,TVDBDeferred):
                # A shared TVDB cooldown is temporary, never a no-match verdict.
                attempts-=1
                decision="LOOKUP_RETRY"
                report={"decision":decision,"issues":["TVDB_HTTP_COOLDOWN"]}
                retry=True
                retry_delay=exc.retry_after_seconds+1
                pending_retries+=1
            elif isinstance(exc,AniDBLookupDeferred):
                # A shared AniDB cooldown is a wait, not a failed identity.
                attempts-=1
                decision="LOOKUP_RETRY"
                report={"decision":decision,"issues":["ANIDB_HTTP_COOLDOWN"]}
                retry=True
                retry_delay=exc.retry_after_seconds+1
                pending_retries+=1
            else:
                decision="LOOKUP_RETRY" if attempts<3 else "NEEDS_REVIEW"
                report={"decision":decision,"issues":["LOOKUP_"+type(exc).__name__]}
                retry=attempts<3
                pending_retries+=int(retry)
                event(LOG, logging.ERROR, "IDENTITY_UNEXPECTED_FAILURE",
                      subsystem="identity", stage=stage, outcome=decision,
                      notification_id=nid, attempt=attempts,
                      error_type=type(exc).__name__,
                      elapsed_ms=span.milliseconds(), retryable=retry,
                      exc_info=True)
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
                (nid,now,attempts,now+(retry_delay if retry_delay is not None else min(3600,60*2**attempts)) if retry else 0,decision,safe))
            if decision=="BATCH_VERIFIED":
                db.execute("UPDATE notifications SET status='APPROVED_BATCH' WHERE id=? AND status='IDENTIFYING'",(nid,))
            elif not retry and decision!="AUTO_VERIFIED":
                db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=? AND status='IDENTIFYING'",(nid,))
        if decision=="BATCH_VERIFIED" and mapping_xml is not None:
            from anime_verified_season_memory import remember_from_authorized_batch
            try:
                remember_from_authorized_batch(db,nid,mapping_xml)
            except ValueError as exc:
                LOG.warning("event=VERIFIED_BATCH_CACHE_REVIEW notification=%d reason=%s",
                            nid,type(exc).__name__)
        event(LOG, logging.INFO, "IDENTITY_FINISHED", subsystem="identity",
              notification_id=nid, attempt=attempts, outcome=decision,
              elapsed_ms=span.milliseconds(), retryable=retry)
        LOG.info("identity finalized notification=%s attempt=%s persisted_decision=%s retry=%s",
                 nid,attempts,decision,retry)
        done+=1
    return {"processed":done,"pending_retries":pending_retries}

