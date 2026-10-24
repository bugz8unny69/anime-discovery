"""Hash-addressed metainfo reads from an operator-configured HTTP(S) source.

No download-client writes, arbitrary delivery URLs, redirects, ambient proxies,
or persistent copies of tracker/passkey-bearing metainfo are used here.
"""
from dataclasses import dataclass, field
import asyncio
import http.client
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from src.nextgen.async_io import blocking
from src.nextgen.acquisition.metadata import MAX_METAINFO, MetadataInvalid, infohash, parse_metainfo
from src.nextgen.acquisition.settings import endpoint


class MetadataSourceConfigurationError(ValueError):
    reason_code='TORRENT_METADATA_CONFIGURATION_INVALID'
    def __init__(self):super().__init__('Configure the torrent metadata source before downloading.')


class MetadataSourceUnavailable(RuntimeError):
    reason_code='TORRENT_METADATA_UNAVAILABLE'
    def __init__(self):super().__init__('The torrent metadata source is temporarily unavailable.')


class MetadataSourceDenied(ValueError):
    reason_code='TORRENT_METADATA_DENIED'
    def __init__(self):super().__init__('The torrent metadata source refused access.')


class MetadataSourceWaiting(RuntimeError):
    reason_code='TORRENT_METADATA_WAITING'
    def __init__(self,delay_ms=60000):
        self.delay_ms=delay_ms
        super().__init__('Waiting for the torrent metadata source.')


def source_url(value):
    """An operator supplies a base folder, never a format string or a query token."""
    try:
        if type(value) is not str or not value or len(value)>2048:raise ValueError()
        parsed=urllib.parse.urlsplit(value)
        authority=endpoint(urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'','','')))
        if (parsed.query or parsed.fragment or '?' in value or '#' in value or '%' in value
                or '\\' in value or not value.isascii() or any(ord(c)<=32 or ord(c)==127 for c in value)):
            raise ValueError()
        path=parsed.path.rstrip('/')
        if path and (not path.startswith('/') or any(not re.fullmatch('[A-Za-z0-9_-]+',p) for p in path[1:].split('/'))):
            raise ValueError()
        return authority+path
    except (ValueError,TypeError,AttributeError):raise MetadataSourceConfigurationError() from None


@dataclass(frozen=True)
class SourceOptions:
    base_url: str = field(repr=False)
    timeout_seconds: int
    def __post_init__(self):
        object.__setattr__(self,'base_url',source_url(self.base_url))
        if type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=60:raise MetadataSourceConfigurationError()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def _status(code,headers):
    if code==200:return
    if code in (401,403):raise MetadataSourceDenied()
    if code in (404,429,503):
        retry=headers.get('Retry-After','')
        delay=int(retry)*1000 if type(retry) is str and re.fullmatch('[0-9]{1,5}',retry) else 60000
        raise MetadataSourceWaiting(max(1000,min(delay,86400000)))
    if code in (408,425,500,502,504):raise MetadataSourceUnavailable()
    raise MetadataInvalid()


class Client:
    def __init__(self,options,*,transport=None,clock=time.monotonic):
        if type(options) is not SourceOptions:raise MetadataSourceConfigurationError()
        self.options,self.clock=options,clock
        opener=urllib.request.build_opener(_NoRedirect(),urllib.request.ProxyHandler({}))
        self.transport=transport or (lambda request,timeout:opener.open(request,timeout=timeout))

    def fetch(self,expected_hash,cancelled):
        digest=infohash(expected_hash)
        if cancelled.is_set():raise asyncio.CancelledError()
        # Only a normalized 40-character digest can influence the request path.
        request=urllib.request.Request(self.options.base_url+'/'+digest+'.torrent',headers={
            'User-Agent':'AnimeDiscoveryNextGen/1','Accept':'application/x-bittorrent, application/octet-stream',
            'Accept-Encoding':'identity'},method='GET')
        deadline=self.clock()+self.options.timeout_seconds
        try:
            with self.transport(request,self.options.timeout_seconds) as response:
                _status(response.getcode(),response.headers)
                if response.headers.get('Content-Encoding','identity').lower()!='identity':raise MetadataInvalid()
                declared=response.headers.get('Content-Length')
                if declared is not None and (not re.fullmatch('[0-9]{1,10}',declared) or int(declared)>MAX_METAINFO):raise MetadataInvalid()
                chunks=[];size=0
                while True:
                    if cancelled.is_set():raise asyncio.CancelledError()
                    if self.clock()>=deadline:raise MetadataSourceUnavailable()
                    # read1 avoids accumulating a whole chunk across unlimited
                    # slow partial reads before checking the deadline/cancellation.
                    chunk=response.read1(min(65536,MAX_METAINFO+1-size))
                    if type(chunk) is not bytes:raise MetadataInvalid()
                    if not chunk:break
                    size+=len(chunk)
                    if size>MAX_METAINFO:raise MetadataInvalid()
                    chunks.append(chunk)
                if declared is not None and int(declared)!=size:raise MetadataInvalid()
                raw=b''.join(chunks)
        except urllib.error.HTTPError as exc:
            try:_status(exc.code,exc.headers)
            finally:exc.close()
            raise MetadataInvalid() from None
        except (OSError,TimeoutError,urllib.error.URLError,http.client.HTTPException):
            raise MetadataSourceUnavailable() from None
        if cancelled.is_set():raise asyncio.CancelledError()
        parse_metainfo(raw,digest)
        return raw


def make_reader(*,client_factory=Client):
    """Trusted async callback for preparation and exact-plan submission checks."""
    async def read_metainfo(source,configuration,cancelled):
        if cancelled.is_set():raise asyncio.CancelledError()
        options=SourceOptions(configuration.value('torrent_metadata.base_url'),
                              configuration.value('torrent_metadata.timeout_seconds'))
        client=client_factory(options)
        return await blocking(client.fetch,source.info_hash,cancelled)
    return read_metainfo
