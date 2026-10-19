"""Best-effort review notification through configured private ntfy server."""
import json
import logging
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
LOG=logging.getLogger(__name__)

def notify_review(settings,secrets,notification_id,title,*,opener=urlopen):
    cfg=settings["ntfy"]
    if not cfg["enabled"]:
        return False
    parsed=urlsplit(cfg["server"])
    if parsed.scheme!="https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("NTFY requires HTTPS base URL")
    dashboard=cfg["dashboard_url"].rstrip("/")
    if urlsplit(dashboard).scheme!="https":
        raise ValueError("NTFY requires HTTPS dashboard link")
    url=cfg["server"].rstrip("/")+"/"+quote(cfg["topic"],safe="")
    headers={"Title":"Anime Discovery: Needs Review","Click":dashboard+"/jobs",
             "Content-Type":"text/plain; charset=utf-8"}
    token=secrets.get("ntfy_token")
    if token:
        headers["Authorization"]="Bearer "+token
    request=Request(url,data=("Release needs review: "+str(title)[:160]).encode("utf-8"),
                    method="POST",headers=headers)
    with opener(request,timeout=8) as response:
        if response.status not in (200,201,202):
            raise RuntimeError("NTFY delivery rejected")
    return True

def notify_best_effort(settings,secrets,notification_id,title):
    try:
        return notify_review(settings,secrets,notification_id,title)
    except Exception as exc:
        LOG.warning("NTFY delivery failed (%s)",type(exc).__name__)
        return False
