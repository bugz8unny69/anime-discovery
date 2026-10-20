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

def notify_shoko_issue(settings,secrets,series_id,notification_id,reason,*,opener=urlopen):
    """Best-effort manual Shoko attention alert; no API keys or paths in message."""
    cfg=settings["ntfy"]
    if not cfg["enabled"]:
        return False
    parsed=urlsplit(cfg["server"])
    if parsed.scheme!="https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("NTFY requires HTTPS origin")
    dashboard=cfg["dashboard_url"].rstrip("/")
    if urlsplit(dashboard).scheme!="https":
        raise ValueError("NTFY requires HTTPS dashboard")
    url=cfg["server"].rstrip("/")+"/"+quote(cfg["topic"],safe="")
    headers={"Title":"Anime Discovery: Shoko needs attention",
             "Click":dashboard+"/jobs",
             "Priority":"4","Content-Type":"text/plain; charset=utf-8"}
    token=secrets.get("ntfy_token")
    if token:
        headers["Authorization"]="Bearer "+token
    message=("Sonarr Keep completed, but Shoko episode matching needs manual review. "
             "Anime Discovery series "+str(series_id)+", notification "+str(notification_id)+
             ". Status: "+str(reason)[:80]+". Permanent Sonarr files are retained.")
    with opener(Request(url,data=message.encode(),method="POST",headers=headers),timeout=8) as response:
        if response.status not in (200,201,202):
            raise RuntimeError("NTFY Shoko alert rejected")
    return True


def notify_sonarr_duplicate(settings,secrets,series_id,title,*,opener=urlopen):
    """Actionable alert only; never authorizes any deletion."""
    cfg=settings["ntfy"]
    if not cfg["enabled"]:return False
    parsed=urlsplit(cfg["server"])
    dashboard=cfg["dashboard_url"].rstrip("/")
    if (parsed.scheme!="https" or not parsed.netloc or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or urlsplit(dashboard).scheme!="https"):
        raise ValueError("NTFY requires trusted HTTPS URLs")
    if type(series_id) is not int or series_id<=0:
        raise ValueError("Invalid series ID")
    headers={"Title":"Anime Discovery: Sonarr has trial episodes",
             "Click":dashboard+"/series?id="+str(series_id),
             "Priority":"3","Content-Type":"text/plain; charset=utf-8"}
    token=secrets.get("ntfy_token")
    if token:headers["Authorization"]="Bearer "+token
    request=Request(cfg["server"].rstrip("/")+"/"+quote(cfg["topic"],safe=""),
                    data=("Sonarr already manages trial episodes for "+str(title)[:120]+
                          ". Review them in Anime Discovery; no files were deleted.").encode(),
                    method="POST",headers=headers)
    with opener(request,timeout=8) as response:
        if response.status not in (200,201,202):
            raise RuntimeError("NTFY alert rejected")
    return True
