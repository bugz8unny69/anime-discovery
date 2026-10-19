"""Bounded administrator-triggered integration probes; never echo credentials."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote,urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def origin(url,*,https_only=False):
    parsed=urlsplit(url)
    if (parsed.scheme not in (("https",) if https_only else ("http","https"))
        or not parsed.hostname or parsed.username or parsed.password or parsed.query
        or parsed.fragment or parsed.path not in ("","/")):
        raise ValueError("Invalid integration origin")
    return url.rstrip("/")

def test_connection(settings,secrets,service,*,opener=None):
    if service=="autobrr":
        return {"service":service,"tested":False,
                "message":"Incoming webhook: use Autobrr's own test event."}
    if service not in ("jellyfin","sonarr","shoko","ntfy"):
        raise ValueError("Unknown integration")
    cfg=settings[service]
    if not cfg.get("enabled"):
        return {"service":service,"tested":False,"message":"Integration disabled"}
    if opener is None:
        opener=build_opener(NoRedirect()).open
    if service=="ntfy":
        url=origin(cfg["server"],https_only=True)+"/"+quote(cfg["topic"],safe="")
        headers={"Title":"Anime Discovery connection test","Content-Type":"text/plain"}
        if secrets.get("ntfy_token"):
            headers["Authorization"]="Bearer "+secrets["ntfy_token"]
        request=Request(url,data=b"Anime Discovery connection test",
                        method="POST",headers=headers)
    else:
        path={"jellyfin":"/System/Info","sonarr":"/api/v3/system/status",
              "shoko":"/api/v3/Init/Status"}[service]
        url=origin(cfg["base_url"])+path
        headers={"Accept":"application/json"}
        key={"jellyfin":"jellyfin_api_key","sonarr":"sonarr_api_key",
             "shoko":"shoko_api_key"}[service]
        if not secrets.get(key):
            return {"service":service,"tested":False,"message":"Credential not configured"}
        headers[{"jellyfin":"X-Emby-Token","sonarr":"X-Api-Key",
                 "shoko":"apikey"}[service]]=secrets[key]
        request=Request(url,headers=headers)
    try:
        with opener(request,timeout=8) as response:
            status=response.status
            if status not in (200,201,202):
                raise RuntimeError("Unexpected response code")
            if service!="ntfy":
                payload=json.loads(response.read(65536))
                if not isinstance(payload,dict):
                    raise ValueError("Invalid service response")
                if service=="sonarr" and not payload.get("version"):
                    raise ValueError("Sonarr system status missing version")
            return {"service":service,"tested":True,"connected":True,
                    "message":"Connection verified" if service!="ntfy" else "Test notification accepted"}
    except HTTPError as exc:
        return {"service":service,"tested":True,"connected":False,
                "message":"HTTP "+str(exc.code)}
    except (URLError,TimeoutError,OSError) as exc:
        return {"service":service,"tested":True,"connected":False,
                "message":"Network failure ("+type(exc).__name__+")"}
    except (ValueError,RuntimeError,json.JSONDecodeError) as exc:
        return {"service":service,"tested":True,"connected":False,
                "message":"Invalid response ("+type(exc).__name__+")"}
