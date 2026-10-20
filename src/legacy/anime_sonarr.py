"""Idempotent Sonarr series admission; does not move or delete trial media."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

def _request(base_url, api_key, method, path, payload=None, *, opener=urlopen):
    parsed=urlsplit(base_url)
    if parsed.scheme not in ("http","https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("","/"):
        raise ValueError("Invalid Sonarr base URL")
    if not isinstance(api_key,str) or not api_key.strip():
        raise ValueError("Sonarr API key required")
    data=None if payload is None else json.dumps(payload).encode("utf-8")
    req=Request(base_url.rstrip("/")+"/api/v3/"+path, data=data, method=method,
                headers={"X-Api-Key":api_key, "Accept":"application/json",
                         "Content-Type":"application/json"})
    try:
        with opener(req,timeout=10) as response:
            raw=response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        # Avoid logging credentials or upstream response bodies.
        raise RuntimeError("Sonarr API returned HTTP "+str(exc.code)) from None

def ensure_series(settings, secrets, *, tvdb_id, title, opener=urlopen):
    sonarr=settings["sonarr"]
    if sonarr["enabled"] is not True:
        raise ValueError("Sonarr integration disabled")
    tvdb=int(tvdb_id)
    if tvdb<=0:
        raise ValueError("Verified TVDB ID required")
    key=secrets.get("sonarr_api_key")
    url=sonarr["base_url"]
    profiles=_request(url,key,"GET","qualityprofile",opener=opener)
    profile_name=sonarr.get("quality_profile_name","Anime")
    named=[p for p in profiles if isinstance(p,dict) and p.get("name")==profile_name] if isinstance(profiles,list) else []
    if len(named)!=1 or type(named[0].get("id")) is not int:
        raise RuntimeError("Configured Sonarr quality profile name is missing or ambiguous")
    profile_id=named[0]["id"]
    if sonarr["quality_profile_id"] and sonarr["quality_profile_id"]!=profile_id:
        raise RuntimeError("Sonarr profile ID does not match configured name")
    roots=_request(url,key,"GET","rootfolder",opener=opener)
    if not isinstance(roots,list) or not any(p.get("path")==sonarr["root_folder"] for p in roots):
        raise RuntimeError("Configured Sonarr root folder is not registered")
    existing=_request(url,key,"GET","series",opener=opener)
    if not isinstance(existing,list):
        raise RuntimeError("Unexpected Sonarr series response")
    for item in existing:
        if item.get("tvdbId")==tvdb:
            return {"sonarr_id":item["id"],"already_exists":True}
    lookup=_request(url,key,"GET","series/lookup?term=tvdb:"+str(tvdb),opener=opener)
    if not isinstance(lookup,list) or not lookup:
        raise RuntimeError("TVDB identity not found by Sonarr")
    matches=[item for item in lookup if item.get("tvdbId")==tvdb]
    if len(matches)!=1:
        raise RuntimeError("TVDB lookup ambiguous")
    series=dict(matches[0])
    if series.get("id"):
        series.pop("id")
    series.update({"tvdbId":tvdb,"qualityProfileId":profile_id,
                   "rootFolderPath":sonarr["root_folder"],
                   "seasonFolder":True,"monitored":True,
                   "monitorNewItems":"all","seriesType":"anime",
                   # Keep is the user's decision to follow this show from
                   # now on. Do not start an unbounded historical search.
                   "addOptions":{"monitor":"all","searchForMissingEpisodes":False}})
    result=_request(url,key,"POST","series",series,opener=opener)
    if not isinstance(result,dict) or not isinstance(result.get("id"),int):
        raise RuntimeError("Sonarr did not confirm series admission")
    return {"sonarr_id":result["id"],"already_exists":False}
