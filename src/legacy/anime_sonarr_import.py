"""Fail-closed Sonarr manual-import handoff.

Never requests MOVE. No torrent deletion; cleanup requires separate ownership proof.
"""
from pathlib import Path
from anime_sonarr import _request

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

def request_import(settings,secrets,*,sonarr_id,plan,opener=None):
    """Request COPY only when Sonarr maps each exact source path to the expected episode."""
    cfg=settings["sonarr"]
    key=secrets["sonarr_api_key"]
    kwargs={} if opener is None else {"opener":opener}
    episodes=_request(cfg["base_url"],key,"GET","episode?seriesId="+str(sonarr_id),**kwargs)
    if not isinstance(episodes,list):
        raise RuntimeError("Invalid Sonarr episode inventory")
    selected=[]
    for item in plan:
        matches=[e for e in episodes if e.get("seasonNumber")==item["season"] and e.get("episodeNumber")==item["episode"]]
        if len(matches)!=1 or type(matches[0].get("id")) is not int:
            raise RuntimeError("Sonarr episode identity not unique")
        # Sonarr must have access to these exact staged files through a shared mount.
        candidates=_request(cfg["base_url"],key,"GET",
            "manualimport?folder="+__import__("urllib.parse",fromlist=["quote"]).quote(str(Path(item["path"]).parent),safe=""),**kwargs)
        if not isinstance(candidates,list):
            raise RuntimeError("Invalid Sonarr manual import candidates")
        matches_file=[c for c in candidates if c.get("path")==item["path"]
                      and c.get("series",{}).get("id")==sonarr_id
                      and any(e.get("id")==matches[0]["id"] for e in c.get("episodes",[]))]
        if len(matches_file)!=1:
            raise RuntimeError("Sonarr did not identify exact staged file and episode")
        candidate=matches_file[0]
        if not candidate.get("quality") or not candidate.get("languages"):
            raise RuntimeError("Sonarr import quality/language mapping incomplete")
        selected.append({"path":item["path"],"seriesId":sonarr_id,
                         "episodeIds":[matches[0]["id"]],
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
