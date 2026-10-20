"""Fail-closed Sonarr manual-import handoff.

Never requests MOVE. No torrent deletion; cleanup requires separate ownership proof.
"""
from pathlib import Path
import logging
from urllib.parse import quote

from anime_sonarr import _request

LOG = logging.getLogger("anime_discovery.sonarr")


class SonarrImportNeedsReview(RuntimeError):
    """Safe, actionable Sonarr candidate mismatch; no import was submitted."""

    def __init__(self, reason, message):
        self.reason = reason
        super().__init__(message)


def _candidate_review(reason, *, sonarr_id, item, count, message):
    LOG.warning(
        "event=SONARR_KEEP_REVIEW reason=%s sonarr_id=%s season=%s episode=%s candidates=%d",
        reason, sonarr_id, item["season"], item["episode"], count)
    raise SonarrImportNeedsReview(reason, message)

def plan_staged_imports(db,series_id,*,trial_root):
    root=Path(trial_root).resolve(strict=True)
    rows=db.execute("""SELECT d.notification_id,d.season,d.episode,r.staged_path
        FROM episode_dispatch d JOIN torrent_recovery_records r
        ON r.notification_id=d.notification_id
        WHERE d.series_id=? AND d.state='DONE'
        ORDER BY d.season,d.episode""",(series_id,)).fetchall()
    if not rows:
        raise ValueError("No completed staged episodes")
    plan=[]
    seen=set()
    for nid,season,episode,filename in rows:
        file=Path(filename)
        path=file.resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(root) or path==root:
            raise ValueError("Staged file outside trusted trial root")
        if path in seen:
            raise ValueError("Duplicate trial file")
        seen.add(path)
        if type(season) is not int or type(episode) is not int or season<0 or episode<=0:
            raise ValueError("Invalid staged episode numbering")
        plan.append({"notification_id":nid,"season":season,"episode":episode,"path":str(path)})
    return plan

def _reprocess_verified_identity(cfg, key, sonarr_id, item, candidate, episode_id, kwargs):
    """Ask Sonarr to re-evaluate its *exact* discovered file with trusted IDs.

    A staged S01E01.mkv may not contain enough title information for Sonarr
    to auto-match. POST /manualimport reprocesses a preview; it does NOT
    import anything. Only the later explicit ManualImport command can copy.
    Sonarr must independently confirm quality, languages and no rejections.
    """
    quality=candidate.get("quality")
    languages=candidate.get("languages")
    if not isinstance(quality,dict) or not isinstance(languages,list):
        _candidate_review(
            "QUALITY_LANGUAGE_UNRESOLVED",sonarr_id=sonarr_id,item=item,count=1,
            message="Sonarr sees the staged file but did not return usable quality/language metadata. Review Wanted > Manual Import.")
    payload=[{
        "path":item["path"],"seriesId":sonarr_id,
        "seasonNumber":item["season"],"episodeIds":[episode_id],
        "quality":quality,"languages":languages,
        "releaseGroup":candidate.get("releaseGroup") or "",
        "indexerFlags":candidate.get("indexerFlags") or 0,
        "releaseType":candidate.get("releaseType") or "unknown"
    }]
    processed=_request(cfg["base_url"],key,"POST","manualimport",payload,**kwargs)
    if not isinstance(processed,list) or len(processed)!=1 or not isinstance(processed[0],dict):
        _candidate_review(
            "SONARR_REPROCESS_UNCONFIRMED",sonarr_id=sonarr_id,item=item,count=1,
            message="Sonarr did not confirm the explicit series and episode assignment. No import was requested.")
    confirmed=processed[0]
    actual_eps=confirmed.get("episodes")
    if (confirmed.get("path")!=item["path"] or
            confirmed.get("seriesId")!=sonarr_id or
            not isinstance(actual_eps,list) or len(actual_eps)!=1 or
            not isinstance(actual_eps[0],dict) or actual_eps[0].get("id")!=episode_id):
        _candidate_review(
            "SONARR_REPROCESS_IDENTITY_MISMATCH",sonarr_id=sonarr_id,item=item,count=1,
            message="Sonarr did not confirm the supplied TVDB-backed series and canonical episode. Review Sonarr episode numbering.")
    if confirmed.get("rejections"):
        _candidate_review(
            "SONARR_REJECTED_CANDIDATE",sonarr_id=sonarr_id,item=item,count=1,
            message="Sonarr rejected the explicitly reprocessed manual-import candidate. Review Wanted > Manual Import.")
    if not isinstance(confirmed.get("quality"),dict) or not confirmed.get("languages"):
        _candidate_review(
            "QUALITY_LANGUAGE_UNRESOLVED",sonarr_id=sonarr_id,item=item,count=1,
            message="Sonarr could not establish quality and language for the verified staged file.")
    LOG.info(
        "event=SONARR_MANUAL_IMPORT_MAPPED reason=EXPLICIT_VERIFIED_EPISODE "
        "sonarr_id=%d season=%d episode=%d",
        sonarr_id,item["season"],item["episode"])
    return confirmed


def request_import(settings,secrets,*,sonarr_id,plan,opener=None):
    """Add existing verified files by explicit Sonarr IDs, never parser guesses.

    Caller has already admitted the series into Sonarr through ensure_series.
    Sonarr has to see each exact staged path; its filename-derived series or
    episode prediction is *not* the authority. If a prediction is missing or
    wrong, reprocess it with the known series and canonical episode IDs.
    This is an identity preview, followed by a COPY command only after all
    candidates are verified and un-rejected.
    """
    cfg=settings["sonarr"]
    key=secrets["sonarr_api_key"]
    kwargs={} if opener is None else {"opener":opener}
    episodes=_request(cfg["base_url"],key,"GET","episode?seriesId="+str(sonarr_id),**kwargs)
    if not isinstance(episodes,list):
        raise RuntimeError("Invalid Sonarr episode inventory")
    selected=[]
    for item in plan:
        matches=[e for e in episodes if isinstance(e,dict) and
                 e.get("seasonNumber")==item["season"] and
                 e.get("episodeNumber")==item["episode"]]
        if len(matches)!=1 or type(matches[0].get("id")) is not int:
            _candidate_review(
                "SONARR_EPISODE_NOT_FOUND" if not matches else "SONARR_EPISODE_AMBIGUOUS",
                sonarr_id=sonarr_id,item=item,count=0,
                message=("The expected season/episode is absent or ambiguous in Sonarr's "
                         "episode inventory. Check the series TVDB identity, season "
                         "numbering, and Sonarr episode refresh before retrying Keep."))
        eid=matches[0]["id"]
        # Do not supply seriesId on this GET: Sonarr interprets that as a
        # request to scan the *series library*, not the Anime-Trial folder.
        candidates=_request(cfg["base_url"],key,"GET",
            "manualimport?folder="+quote(str(Path(item["path"]).parent),safe=""),**kwargs)
        if not isinstance(candidates,list):
            raise RuntimeError("Invalid Sonarr manual import candidates")
        same_path=[c for c in candidates if isinstance(c,dict)
                   and c.get("path")==item["path"]]
        if len(same_path)!=1:
            reason=("SOURCE_FOLDER_NOT_VISIBLE" if not candidates else
                    "STAGED_FILE_PATH_NOT_VISIBLE" if not same_path else
                    "AMBIGUOUS_IMPORT_CANDIDATES")
            message=(
                "Sonarr returned no files from Anime-Trial. Verify that its "
                "service can read this staged folder with Wanted > Manual Import."
                if not candidates else
                "Sonarr cannot see the exact Anime-Trial staged file. Check "
                "the NFS or container path mapping and file permissions."
                if not same_path else
                "Sonarr returned duplicate candidates for one staged file. "
                "Review its manual-import inventory.")
            _candidate_review(reason,sonarr_id=sonarr_id,item=item,
                              count=len(candidates),message=message)
        candidate=same_path[0]
        parsed_series=candidate.get("series")
        parsed_episodes=candidate.get("episodes") or []
        parser_confirmed=(isinstance(parsed_series,dict) and
            parsed_series.get("id")==sonarr_id and
            isinstance(parsed_episodes,list) and len(parsed_episodes)==1 and
            isinstance(parsed_episodes[0],dict) and
            parsed_episodes[0].get("id")==eid)
        if not parser_confirmed:
            # Do NOT reject a title-less S01E01.mkv just because Sonarr's
            # filename parser was unable to supply the known series/episode.
            candidate=_reprocess_verified_identity(
                cfg,key,sonarr_id,item,candidate,eid,kwargs)
        if candidate.get("rejections"):
            _candidate_review(
                "SONARR_REJECTED_CANDIDATE",sonarr_id=sonarr_id,item=item,
                count=len(candidates),
                message="Sonarr rejected the manual-import candidate. Review its reasons in Wanted > Manual Import before retrying Keep.")
        if not isinstance(candidate.get("quality"),dict) or not candidate.get("languages"):
            _candidate_review(
                "QUALITY_LANGUAGE_UNRESOLVED",sonarr_id=sonarr_id,item=item,
                count=len(candidates),
                message="Sonarr could not determine the staged episode quality or language. Review Wanted > Manual Import before retrying Keep.")
        selected.append({"path":item["path"],"seriesId":sonarr_id,
                         "episodeIds":[eid],
                         "quality":candidate["quality"],"languages":candidate["languages"]})
    command=_request(cfg["base_url"],key,"POST","command",
        {"name":"ManualImport","files":selected,"importMode":"copy"},**kwargs)
    if not isinstance(command,dict) or type(command.get("id")) is not int:
        raise RuntimeError("Sonarr did not accept manual import command")
    return {"command_id":command["id"],"submitted":len(selected),
            "source_cleanup_authorized":False,"torrent_cleanup_authorized":False}


def verify_import(settings,secrets,*,sonarr_id,plan,opener=None):
    """Only reports verification; caller must separately verify torrent transfer."""
    cfg=settings["sonarr"]
    kwargs={} if opener is None else {"opener":opener}
    files=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET",
                   "episodefile?seriesId="+str(sonarr_id),**kwargs)
    episodes=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET",
                      "episode?seriesId="+str(sonarr_id),**kwargs)
    if not isinstance(files,list) or not isinstance(episodes,list):
        raise RuntimeError("Invalid Sonarr file inventory")
    ids={e["id"]:(e.get("seasonNumber"),e.get("episodeNumber"),e.get("episodeFileId"))
         for e in episodes if type(e.get("id")) is int}
    for item in plan:
        matching=[file for file in files if any(
            data[0]==item["season"] and data[1]==item["episode"] and data[2]==file.get("id")
            for data in ids.values())]
        if len(matching)!=1 or not matching[0].get("path"):
            return False
        if not Path(matching[0]["path"]).is_file():
            return False
    return True
