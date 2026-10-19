"""Read-only TVDB v4 identity lookup. Does not auto-approve ambiguous releases."""
import json
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

def lookup_tvdb(settings,secrets,tvdb_id,*,opener=urlopen):
    cfg=settings["tvdb"]
    if cfg["enabled"] is not True:
        raise ValueError("TVDB integration disabled")
    if type(tvdb_id) not in (str,int) or not str(tvdb_id).isdigit() or int(tvdb_id)<=0:
        raise ValueError("Valid TVDB ID required")
    base=cfg["base_url"].rstrip("/")
    parsed=urlsplit(base)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("TVDB API URL must use HTTPS")
    key=secrets.get("tvdb_api_key")
    if not isinstance(key,str) or not key:
        raise ValueError("TVDB API key required")
    login=Request(base+"/login",data=json.dumps({"apikey":key}).encode(),
                  method="POST",headers={"Content-Type":"application/json"})
    with opener(login,timeout=10) as res:
        auth=json.loads(res.read())
    token=auth.get("data",{}).get("token")
    if not isinstance(token,str) or not token:
        raise RuntimeError("TVDB login unsuccessful")
    req=Request(base+"/series/"+str(int(tvdb_id)),headers={"Authorization":"Bearer "+token})
    with opener(req,timeout=10) as res:
        payload=json.loads(res.read())
    record=payload.get("data")
    if not isinstance(record,dict) or str(record.get("id"))!=str(int(tvdb_id)):
        raise RuntimeError("TVDB identity mismatch")
    return {"tvdb_id":int(tvdb_id),"name":record.get("name") or ""}
