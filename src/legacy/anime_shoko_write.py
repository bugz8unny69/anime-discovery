"""Shoko 5.3.3 API scan/link operations; isolated from Sonarr Keep.

Only call when explicit episode identity is verified and auto-link enabled.
A linked association must be read back; writes never touch physical files.
"""
import json
from urllib.request import Request,urlopen
from anime_shoko_v3 import _get

def _origin(base_url):
    from urllib.parse import urlsplit
    p=urlsplit(base_url)
    if p.scheme not in ("http","https") or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ("","/"):
        raise ValueError("Shoko origin invalid")
    return base_url.rstrip("/")

def request_scan(base_url,key,folder_id,*,opener=urlopen):
    if type(folder_id) is not int or folder_id<=0:
        raise ValueError("Configured import folder ID required")
    # Swagger specifies GET, but this endpoint has side effects.
    url=_origin(base_url)+"/api/v3/ImportFolder/"+str(folder_id)+"/Scan"
    with opener(Request(url,headers={"apikey":key,"Accept":"application/json"}),timeout=15) as resp:
        if resp.status!=200:
            raise RuntimeError("Shoko scan rejected")
    return True

def linked_episode_ids(base_url,key,file_id,*,opener=urlopen):
    if type(file_id) is not int or file_id<=0:
        raise ValueError("Shoko file ID required")
    result=_get(base_url,key,"File/"+str(file_id)+"/Episode",opener=opener)
    if not isinstance(result,list):
        raise RuntimeError("Shoko episode readback unavailable")
    pairs=set()
    for ep in result:
        if not isinstance(ep,dict) or not isinstance(ep.get("IDs"),dict):
            raise RuntimeError("Malformed Shoko linked episode")
        ids=ep["IDs"]
        if type(ids.get("ID")) is not int or type(ids.get("AniDB")) is not int:
            raise RuntimeError("Missing linked episode identity")
        pairs.add((ids["ID"],ids["AniDB"]))
    return pairs

def confirm_association(base_url,key,*,file_id,shoko_episode_id,anidb_episode_id,opener=urlopen):
    actual=linked_episode_ids(base_url,key,file_id,opener=opener)
    expected=(shoko_episode_id,anidb_episode_id)
    if actual=={expected}:
        return True
    if actual:
        raise RuntimeError("Shoko file linked to unexpected or multiple episodes")
    return False

def link_verified(base_url,key,*,file_id,shoko_episode_id,anidb_episode_id,
                  verified_identity,allow_writes=False,opener=urlopen):
    if verified_identity is not True or allow_writes is not True:
        raise ValueError("Verified episode identity and explicit write permission required")
    if any(type(x) is not int or x<=0 for x in
           (file_id,shoko_episode_id,anidb_episode_id)):
        raise ValueError("Exact Shoko and AniDB IDs required")
    if confirm_association(base_url,key,file_id=file_id,
        shoko_episode_id=shoko_episode_id,anidb_episode_id=anidb_episode_id,opener=opener):
        return "SHOKO_ALREADY_LINKED_VERIFIED"
    url=_origin(base_url)+"/api/v3/File/"+str(file_id)+"/Link"
    body=json.dumps({"EpisodeIDs":[shoko_episode_id]}).encode()
    request=Request(url,data=body,method="POST",headers={"apikey":key,
        "Content-Type":"application/json","Accept":"application/json"})
    with opener(request,timeout=15) as resp:
        if resp.status!=200:
            raise RuntimeError("Shoko episode link rejected")
    if not confirm_association(base_url,key,file_id=file_id,
        shoko_episode_id=shoko_episode_id,anidb_episode_id=anidb_episode_id,opener=opener):
        raise RuntimeError("Shoko link not confirmed by readback")
    return "SHOKO_LINK_VERIFIED"
