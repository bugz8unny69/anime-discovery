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
from src.nextgen.acquisition.metadata import MAX_METAINFO, MetadataInvalid, infohash, parse_metainfo, parse_batch_metainfo
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

    def fetch(self,expected_hash,cancelled,*,batch=False):
        if type(batch) is not bool:raise ValueError('invalid metadata inspection mode')
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
        (parse_batch_metainfo if batch else parse_metainfo)(raw,digest)
        return raw


def make_reader(*,client_factory=Client,secrets=None):
    """One metainfo reader for preparation and exact-plan submission checks.

    The configured hash-addressed .torrent source is tried first. Verified
    backfill sources fall back to the magnet in their delivery; ordinary
    webhooks without a configured source fall back to their own hash-bound
    magnet. Either way qBittorrent 5.2+ fetches metadata only, and the bytes
    are re-verified against the hash.
    """
    async def read_metainfo(source,configuration,cancelled):
        if cancelled.is_set():raise asyncio.CancelledError()
        identity=None
        if secrets is not None:
            from src.nextgen.storage.sonarr_selection import acquisition_identity
            identity=await blocking(acquisition_identity,
                configuration.value('storage.database_path'),source)
        try:
            options=SourceOptions(configuration.value('torrent_metadata.base_url'),
                                  configuration.value('torrent_metadata.timeout_seconds'))
            return await blocking(client_factory(options).fetch,
                                  source.info_hash,cancelled)
        except (MetadataSourceConfigurationError,MetadataSourceWaiting,
                MetadataSourceUnavailable) as original_error:
            # A verified backfill event may always fall back. An ordinary
            # webhook falls back only when no .torrent source is configured.
            if secrets is None or identity is None and type(
                    original_error) is not MetadataSourceConfigurationError:raise
            fallback_error=original_error
        # Both backfill and webhook deliveries carry a sanitized hash-bound
        # magnet (credentialed trackers removed; Legacy behavior).
        from src.nextgen.acquisition.qbittorrent import Client as QbClient
        from src.nextgen.acquisition.settings import download_options
        from src.nextgen.acquisition.submission import (
            ClientUnavailable,ClientAuthenticationFailed,ClientInvalid,ClientUnsupported,
        )
        try:
            qb=QbClient(download_options(configuration),
                        await blocking(secrets.qbittorrent_credentials))
            await blocking(qb.login)
            if qb.metadata_strategy!='fetch':
                # Older qBittorrent needs a pre-manifest send journal;
                # the existing .torrent source remains the safe fallback.
                raise fallback_error
            from src.nextgen.storage.acquisition import source_magnet
            magnet=await blocking(source_magnet,
                configuration.value('storage.database_path'),source)
            resolved=await blocking(qb.fetch_metadata,magnet,source.info_hash)
            if resolved is None:raise MetadataSourceWaiting()
            if cancelled.is_set():raise asyncio.CancelledError()
            return resolved[1]
        except ClientUnavailable:raise MetadataSourceUnavailable() from None
        except (ClientAuthenticationFailed,ClientInvalid,ClientUnsupported):
            raise MetadataSourceDenied() from None
    return read_metainfo


def make_batch_reader(*,client_factory=Client):
    """Trusted hash-only reader for VERIFY_RELEASE batch inspection.

    Never used by the strict single-video preparation or submission paths.
    The caller must supply a verified, normalized torrent infohash rather
    than a URL from an incoming notification.
    """
    async def read_batch_metainfo(expected_hash,configuration,cancelled):
        if cancelled.is_set():raise asyncio.CancelledError()
        digest=infohash(expected_hash)
        options=SourceOptions(configuration.value('torrent_metadata.base_url'),
                              configuration.value('torrent_metadata.timeout_seconds'))
        client=client_factory(options)
        return await blocking(client.fetch,digest,cancelled,batch=True)
    return read_batch_metainfo
