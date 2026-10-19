"""Shoko v3 read-only reconciliation using the 5.3.3.0 Swagger contract.

Pinned OpenAPI SHA256: 62c01fb090c77e8ec9340f1768da1fa0f100dbe1fdf24aa0a1c5e0ea9726be80
No file, episode, filesystem or VFS mutations.
"""
import json
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen

def _get(base_url,api_key,path,params=None,*,opener=urlopen):
    u=urlsplit(base_url)
    if u.scheme not in ("http","https") or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("","/"):
        raise ValueError("Invalid Shoko origin")
    if not isinstance(api_key,str) or not api_key:
        raise ValueError("Shoko API key required")
    url=base_url.rstrip("/")+"/api/v3/"+path
    if params:
        url+="?"+urlencode(params)
    req=Request(url,headers={"apikey":api_key,"Accept":"application/json"})
    with opener(req,timeout=10) as response:
        if response.status!=200:
            raise RuntimeError("Shoko read request failed")
        return json.loads(response.read())

def find_file(base_url,api_key,absolute_path,*,opener=urlopen):
    """PathEndsWith is only a candidate search; full absolute path MUST match."""
    if not isinstance(absolute_path,str) or not absolute_path.startswith("/"):
        raise ValueError("Absolute Shoko server path required")
    matches=_get(base_url,api_key,"File/PathEndsWith",{"path":absolute_path,"includeXRefs":"true","limit":100},opener=opener)
    if not isinstance(matches,list):
        raise RuntimeError("Unexpected Shoko file search response")
    exact=[]
    for item in matches:
        if not isinstance(item,dict):
            raise RuntimeError("Unexpected Shoko file entry")
        if any(isinstance(loc,dict) and loc.get("AbsolutePath")==absolute_path and loc.get("IsAccessible") is True for loc in item.get("Locations") or []):
            exact.append(item)
    if not exact:
        return None
    if len(exact)!=1 or type(exact[0].get("ID")) is not int:
        raise RuntimeError("Ambiguous Shoko file match")
    return exact[0]

def resolve_episode(base_url,api_key,anidb_episode_id,*,opener=urlopen):
    if type(anidb_episode_id) is not int or anidb_episode_id<=0:
        raise ValueError("Exact AniDB episode ID required")
    result=_get(base_url,api_key,"Episode/AniDB/"+str(anidb_episode_id)+"/Episode",
                {"includeXRefs":"true"},opener=opener)
    if not isinstance(result,dict):
        raise RuntimeError("Shoko episode not found")
    ids=result.get("IDs")
    if not isinstance(ids,dict) or ids.get("AniDB")!=anidb_episode_id or type(ids.get("ID")) is not int or ids["ID"]<=0:
        raise RuntimeError("Shoko episode identity missing")
    return {"shoko_episode_id":ids["ID"],"episode":result}

def plan_link(*,file_record,shoko_episode_id,anidb_episode_id,identity_verified,ordering_verified):
    """Prepare an unsubmitted POST /File/{fileID}/Link body; never perform it."""
    from anime_shoko_link_plan import plan_episode_link
    if not isinstance(file_record,dict):
        return {"action":"NO_WRITE","reason":"File not found","writes_enabled":False}
    references=file_record.get("SeriesIDs")
    if references is None:
        return {"action":"NO_WRITE","reason":"Unknown existing links","writes_enabled":False}
    existing=[ep for group in references if isinstance(group,dict) for ep in group.get("EpisodeIDs") or []]
    recognized=bool(existing)
    decision=plan_episode_link(contract={"validated":True},
        file_observation={"recognized":recognized,"existing_episode_ids":existing,
                          "file_id":file_record.get("ID")},
        anidb_episode_id=anidb_episode_id,
        identity_verified=identity_verified,episode_order_verified=ordering_verified)
    if decision["action"]!="ELIGIBLE_FOR_SEPARATE_REVIEW":
        return decision
    if type(shoko_episode_id) is not int or shoko_episode_id<=0:
        return {"action":"NO_WRITE","reason":"Shoko episode ID missing","writes_enabled":False}
    return {**decision,"method":"POST","path":"/api/v3/File/"+str(file_record["ID"])+"/Link",
            "body":{"EpisodeIDs":[shoko_episode_id]},"writes_enabled":False}
