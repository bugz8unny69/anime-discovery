"""Read-only Prowlarr torrent candidate search; never initiates downloading.

Use configured multi-indexer search with X-Api-Key kept out of URLs. Results
remain *untrusted hints* until the existing AniDB/TVDB and torrent-manifest
verification pipeline can independently prove their identity and file coverage.
"""
from dataclasses import dataclass,field
import json
import re
from urllib.error import HTTPError,URLError
from urllib.parse import parse_qs,urlsplit,urlencode
from urllib.request import Request,ProxyHandler,HTTPRedirectHandler,build_opener

from src.nextgen.acquisition.settings import endpoint,DownloadConfigurationError
from src.nextgen.providers.release_mapping import declared_episode
from src.nextgen.providers.parsing import release_title,norm


class SearchConfigurationInvalid(ValueError):
    reason_code="MISSING_SEARCH_CONFIGURATION_INVALID"
    def __init__(self):super().__init__("Configure a valid Prowlarr address and private API key.")


class SearchUnavailable(RuntimeError):
    reason_code="MISSING_SEARCH_UNAVAILABLE"
    def __init__(self):super().__init__("Prowlarr search is unavailable.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


@dataclass(frozen=True,repr=False)
class SearchOptions:
    base_url: str
    api_key: str=field(repr=False)
    timeout_seconds: int=15

    def __post_init__(self):
        try:url=endpoint(self.base_url)
        except DownloadConfigurationError:raise SearchConfigurationInvalid() from None
        if (type(self.api_key) is not str or not 8<=len(self.api_key)<=256
                or any(ord(c)<=32 or ord(c)==127 for c in self.api_key)
                or type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=60):
            raise SearchConfigurationInvalid()
        object.__setattr__(self,"base_url",url)


def _infohash(result):
    """Require a real v1 hash in a structured field or a valid magnet btih."""
    value=result.get("infoHash")
    if type(value) is str and re.fullmatch("[a-fA-F0-9]{40}",value):
        return value.lower()
    magnet=result.get("magnetUrl")
    if type(magnet) is not str or len(magnet)>4096:return None
    parsed=urlsplit(magnet)
    if parsed.scheme!="magnet" or parsed.netloc or parsed.path:return None
    xt=parse_qs(parsed.query).get("xt",[])
    if len(xt)!=1:return None
    match=re.fullmatch("urn:btih:([a-fA-F0-9]{40})",xt[0],re.I)
    return match.group(1).lower() if match else None


def candidates(payload,*,series_title,season,episode):
    """Conservative explicit TVDB episode recognition; no AniDB arithmetic."""
    if type(payload) is not list or len(payload)>100:raise SearchUnavailable()
    if (type(series_title) is not str or not series_title or len(series_title)>512
            or type(season) is not int or season<0 or type(episode) is not int or episode<1):
        raise SearchConfigurationInvalid()
    found={}
    for item in payload:
        if type(item) is not dict:continue
        title=item.get("title")
        if (type(title) is not str or not 1<=len(title)<=1024
                or any(ord(c)<32 or ord(c)==127 for c in title)):continue
        try:
            origin,s,n=declared_episode(title)
            if (origin,s,n)!=("tvdb",season,episode):continue
            aliases,_=release_title(title)
            if norm(series_title) not in {norm(alias) for alias in aliases}:continue
        except (ValueError,TypeError):continue
        digest=_infohash(item)
        if not digest:continue
        if digest in found and found[digest]!=title:
            # One hash with conflicting release declarations needs review,
            # never choose a title based on provider ordering.
            found.pop(digest)
            continue
        found[digest]=title
    return tuple(sorted(found.items()))[:25]


class ProwlarrClient:
    def __init__(self,options,*,opener=None):
        if type(options) is not SearchOptions:raise SearchConfigurationInvalid()
        self.options=options
        self._open=opener or build_opener(ProxyHandler({}),_NoRedirect()).open

    def search(self,series_title,season,episode):
        if (type(series_title) is not str or not 1<=len(series_title)<=512
                or any(ord(c)<32 or ord(c)==127 for c in series_title)
                or type(season) is not int or not 0<=season<=999
                or type(episode) is not int or not 1<=episode<=9999):
            raise SearchConfigurationInvalid()
        query=series_title+" S"+str(season).zfill(2)+"E"+str(episode).zfill(2)
        url=self.options.base_url+"/api/v1/search?"+urlencode({
            "query":query,"indexerIds":"-2","type":"search"})
        req=Request(url,headers={"X-Api-Key":self.options.api_key,"Accept":"application/json"})
        try:
            with self._open(req,timeout=self.options.timeout_seconds) as response:
                if response.status!=200:raise SearchUnavailable()
                raw=response.read(1048577)
            if len(raw)>1048576:raise SearchUnavailable()
            return candidates(json.loads(raw),series_title=series_title,
                              season=season,episode=episode)
        except HTTPError as exc:
            if exc.code in (400,401,403,404):raise SearchConfigurationInvalid() from None
            raise SearchUnavailable() from None
        except (URLError,OSError,TimeoutError,UnicodeError,ValueError,TypeError):
            raise SearchUnavailable() from None
