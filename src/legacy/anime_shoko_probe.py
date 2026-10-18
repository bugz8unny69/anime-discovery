"""Read-only Shoko capability probe; no VFS or episode mutations.

Exact episode-link endpoint validation must precede any write integration.
"""
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

def inspect_shoko(base_url, *, opener=None, timeout=10):
    parsed=urlsplit(base_url)
    if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid Shoko URL")
    opener=opener or build_opener()
    request=Request(base_url.rstrip("/")+"/api/v3/Init/Status",
                    headers={"Accept":"application/json"})
    with opener.open(request,timeout=timeout) as response:
        if response.status!=200:
            raise RuntimeError("Shoko status endpoint failed")
        data=json.loads(response.read())
    if not isinstance(data,dict):
        raise ValueError("Invalid Shoko response")
    # A status response does not prove the file-to-AniDB episode write
    # endpoint exists or has compatible semantics.
    return {"reachable":True,"status":data,
            "episode_link_writes_validated":False,
            "writes_enabled":False}
