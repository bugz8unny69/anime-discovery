"""Read-only AniDB HTTP anime episode-ID resolution through a configured HTTPS proxy.

AniDB's native HTTP endpoint is plaintext. Never send it directly from this
worker; require an explicitly configured HTTPS gateway and registered client.
Cache by anime ID to reduce load and respect AniDB's strict rate limits.
"""
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024
MIN_REFRESH_SECONDS = 86400

def parse_episode_id(xml_bytes, aid, epno):
    if type(aid) is not int or aid <= 0 or type(epno) is not int or epno <= 0:
        raise ValueError("Positive AniDB anime and regular episode numbers required")
    if not isinstance(xml_bytes, bytes) or len(xml_bytes) > MAX_BYTES:
        raise ValueError("Invalid AniDB response")
    root=ET.fromstring(xml_bytes)
    if root.tag!="anime" or root.get("id")!=str(aid):
        raise ValueError("AniDB anime identity mismatch")
    found=[]
    for item in root.findall("episodes/episode"):
        no=item.find("epno")
        if no is None or no.get("type")!="1" or not (no.text or "").strip().isdecimal():
            continue
        if int(no.text.strip())==epno:
            eid=item.get("id")
            if not eid or not eid.isdecimal() or int(eid)<=0:
                raise ValueError("Malformed AniDB episode ID")
            found.append(int(eid))
    return found[0] if len(found)==1 else None

def lookup_episode_id(aid, epno, *, endpoint, client, clientver,
                      cache_dir, now=None, opener=urllib.request.urlopen):
    if type(aid) is not int or aid <= 0 or type(epno) is not int or epno <= 0:
        raise ValueError("Invalid AniDB ID")
    parsed=urllib.parse.urlsplit(endpoint)
    if (parsed.scheme!="https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("/httpapi", "/httpapi/")):
        raise ValueError("AniDB HTTP gateway must be HTTPS /httpapi")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3,32}", client or ""):
        raise ValueError("Registered AniDB HTTP client required")
    if type(clientver) is not int or not 1<=clientver<=999999:
        raise ValueError("AniDB client version required")
    now=int(time.time()) if now is None else int(now)
    root=Path(cache_dir)
    path=root/("anime-"+str(aid)+".xml")
    if path.exists() and now-int(path.stat().st_mtime)<MIN_REFRESH_SECONDS:
        return parse_episode_id(path.read_bytes(),aid,epno)
    args=urllib.parse.urlencode({"request":"anime","aid":aid,"protover":1,
                                 "client":client,"clientver":clientver})
    request=urllib.request.Request(endpoint.rstrip("/")+"?"+args,
                                   headers={"User-Agent":"AnimeDiscovery/1.0"})
    with opener(request,timeout=30) as response:
        data=response.read(MAX_BYTES+1)
    if not data or len(data)>MAX_BYTES:
        raise ValueError("AniDB response empty or oversized")
    # Validate the parent before writing a cache file.
    parsed_xml=ET.fromstring(data)
    if parsed_xml.tag!="anime" or parsed_xml.get("id")!=str(aid):
        raise ValueError("AniDB response identity mismatch")
    result=parse_episode_id(data,aid,epno)
    root.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return result
