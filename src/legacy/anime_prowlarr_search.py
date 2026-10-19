"""Prowlarr release search, deliberately confined to verified single episodes.

No torrent is accepted from title similarity alone: the release title must
match a configured series alias and contain a season/episode identifier.
"""
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from anime_release_matching import resolve_release

HASH=re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class ProwlarrClient:
    def __init__(self,base_url,api_key,*,opener=urlopen):
        parsed=urlsplit(base_url)
        if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid Prowlarr URL")
        if not api_key or not isinstance(api_key,str):
            raise ValueError("Prowlarr API key required")
        self.base_url=base_url.rstrip("/")
        self.api_key=api_key
        self.opener=opener

    def search(self,title):
        if not isinstance(title,str) or not title.strip() or len(title)>200:
            raise ValueError("Invalid title query")
        query=urlencode({"query":title,"type":"search"})
        request=Request(self.base_url+"/api/v1/search?"+query,
                        headers={"X-Api-Key":self.api_key,"Accept":"application/json"})
        with self.opener(request,timeout=20) as response:
            content=response.read(2*1024*1024+1)
        if len(content)>2*1024*1024:
            raise ValueError("Prowlarr response too large")
        releases=json.loads(content)
        if not isinstance(releases,list):
            raise ValueError("Unexpected Prowlarr response")
        return releases[:500]


def candidates(releases,*,alias,tvdb_id,anidb_id,season,max_episode=None):
    """One strongest unambiguous candidate per missing episode.

    Only magnet links with an explicit matching BTIH hash are accepted.
    Results requiring a torrent download URL need a different verified path.
    """
    mapped={alias:{"tvdb_id":tvdb_id,"anidb_id":anidb_id,"season":season}}
    by_episode={}
    if max_episode is not None and (type(max_episode) is not int or max_episode<1):
        raise ValueError("Invalid episode bound")
    for release in releases:
        if not isinstance(release,dict):
            continue
        title=release.get("title")
        if not isinstance(title,str):
            continue
        matched=resolve_release(title,mapped)
        if not matched or matched["season"]!=season:
            continue
        episode=matched["episode"]
        if max_episode is not None and episode>max_episode:
            continue
        magnet=release.get("magnetUrl") or release.get("magnet_url")
        if not isinstance(magnet,str):
            continue
        from urllib.parse import parse_qs
        parsed=urlsplit(magnet)
        xt=parse_qs(parsed.query).get("xt",[])
        if parsed.scheme!="magnet" or len(xt)!=1 or not xt[0].lower().startswith("urn:btih:"):
            continue
        infohash=xt[0][9:].lower()
        if not HASH.fullmatch(infohash):
            continue
        seeders=release.get("seeders",0)
        score=seeders if type(seeders) is int and seeders>=0 else 0
        record={"episode":episode,"release_name":title,"info_hash":infohash,
                "magnet_uri":magnet,"seeders":score}
        by_episode.setdefault(episode,[]).append(record)
    selected=[]
    for episode,options in sorted(by_episode.items()):
        unique={o["info_hash"]:o for o in options}
        ordered=sorted(unique.values(),key=lambda o:(-o["seeders"],o["info_hash"]))
        if len(ordered)>1 and ordered[0]["seeders"]==ordered[1]["seeders"]:
            # No confident preference for equally seeded different torrents.
            continue
        selected.append(ordered[0])
    return selected
