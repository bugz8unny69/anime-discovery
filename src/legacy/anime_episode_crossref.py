"""Find exact AniDB episode using independent TVDB and Shoko episode IDs.

Never map episode numbers or offsets. Require a unique TVDB episode record
and a unique Shoko episode with that very TVDB episode ID in the verified
AniDB parent series. If Shoko has no TVDB episode cross-reference, defer.
"""
import json
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
from anime_shoko_v3 import _get

def tvdb_episode_id(settings,secrets,*,tvdb_id,season,episode,opener=urlopen):
    cfg=settings["tvdb"]
    if cfg.get("enabled") is not True or any(type(x) is not int or x<=0 for x in
                                             (tvdb_id,episode)) or type(season) is not int or season<0:
        return None
    base=cfg["base_url"].rstrip("/")
    p=urlsplit(base)
    if p.scheme!="https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("TVDB HTTPS origin required")
    key=secrets.get("tvdb_api_key")
    if not key:
        return None
    login=Request(base+"/login",data=json.dumps({"apikey":key}).encode(),
                  method="POST",headers={"Content-Type":"application/json"})
    with opener(login,timeout=10) as res:
        token=json.loads(res.read()).get("data",{}).get("token")
    if not token:
        raise RuntimeError("TVDB login failed")
    matches=[]
    for page in range(20):
        url=base+"/series/"+str(tvdb_id)+"/episodes/default?"+urlencode({"page":page})
        with opener(Request(url,headers={"Authorization":"Bearer "+token}),
                    timeout=10) as res:
            payload=json.loads(res.read())
        data=payload.get("data")
        episodes=(data.get("episodes") if isinstance(data,dict) else data)
        if not isinstance(episodes,list):
            raise RuntimeError("Unexpected TVDB episode page")
        for entry in episodes:
            if isinstance(entry,dict) and entry.get("seasonNumber")==season and entry.get("number")==episode:
                if type(entry.get("id")) is not int or entry["id"]<=0:
                    raise RuntimeError("TVDB episode identity missing")
                matches.append(entry["id"])
        links=payload.get("links") or {}
        if not isinstance(links,dict) or not links.get("next"):
            break
    else:
        raise RuntimeError("TVDB episode page limit exceeded")
    return matches[0] if len(matches)==1 else None

def resolve_anidb_episode(base_url,key,*,anidb_series_id,tvdb_episode_id,opener=urlopen):
    if any(type(i) is not int or i<=0 for i in (anidb_series_id,tvdb_episode_id)):
        raise ValueError("Exact AniDB series and TVDB episode IDs required")
    opts={"opener":opener}
    series=_get(base_url,key,"Series/AniDB/"+str(anidb_series_id)+"/Series",**opts)
    ids=series.get("IDs") if isinstance(series,dict) else None
    if not isinstance(ids,dict) or ids.get("AniDB")!=anidb_series_id or type(ids.get("ID")) is not int:
        return None
    shoko_series_id=ids["ID"]
    found=[]
    page=1
    while page<=100:
        result=_get(base_url,key,"Series/"+str(shoko_series_id)+"/Episode",
                    {"page":page,"pageSize":100,"includeMissing":"true",
                     "includeUnaired":"true","includeHidden":"true"},**opts)
        if not isinstance(result,dict) or not isinstance(result.get("List"),list) or type(result.get("Total")) is not int:
            raise RuntimeError("Invalid Shoko episode catalog")
        for entry in result["List"]:
            epi=entry.get("IDs") if isinstance(entry,dict) else None
            if not isinstance(epi,dict):
                raise RuntimeError("Incomplete Shoko episode identity")
            refs=epi.get("TvDB") or []
            if not isinstance(refs,list):
                raise RuntimeError("Malformed TVDB episode references")
            if tvdb_episode_id in refs:
                if type(epi.get("AniDB")) is not int or type(epi.get("ID")) is not int:
                    raise RuntimeError("Mapped AniDB episode identity missing")
                if epi.get("ParentSeries")!=shoko_series_id:
                    raise RuntimeError("Shoko episode parent series mismatch")
                found.append(epi["AniDB"])
        if page*100>=result["Total"]:
            break
        page+=1
    else:
        raise RuntimeError("Shoko episode page limit exceeded")
    return found[0] if len(found)==1 else None
