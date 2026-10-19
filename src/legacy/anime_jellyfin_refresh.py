"""Best-effort Jellyfin library refresh after a finalized staged episode."""
import logging
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)

def refresh_library(base_url, api_key, *, timeout=8):
    """Ask Jellyfin to scan libraries. Never include API keys in request URLs."""
    url=base_url.rstrip("/")
    parsed=urlsplit(url)
    if parsed.scheme not in ("http","https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid Jellyfin base URL")
    if not isinstance(api_key,str) or not api_key:
        raise ValueError("Jellyfin API key required")
    request=Request(url+"/Library/Refresh",data=b"",method="POST",
                    headers={"X-Emby-Token":api_key})
    with urlopen(request,timeout=timeout) as response:
        if response.status not in (200,202,204):
            raise RuntimeError("Jellyfin refused library refresh")
    return True

def refresh_best_effort(client):
    if client is None:
        return
    try:
        client()
    except Exception as exc:
        # Never print the URL, credentials, HTTP response body or exception:
        # urllib exceptions can echo private server information.
        LOG.warning("Jellyfin library refresh failed (%s); staged media is retained",
                    type(exc).__name__)
