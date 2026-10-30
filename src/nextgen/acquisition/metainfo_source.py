"""qBittorrent-native torrent metadata access.

No separately configured HTTP source is used. A legacy URL validator remains
only to verify v7-v11 settings *before* dropping them during v12 migration.
"""
import asyncio
import re
import urllib.parse

from src.nextgen.async_io import blocking
from src.nextgen.acquisition.metadata import infohash, MetadataInvalid
from src.nextgen.acquisition.settings import (
    endpoint, download_options, DownloadConfigurationError,
)
from src.nextgen.acquisition.submission import (
    ClientAuthenticationFailed, ClientInvalid, ClientUnavailable, ClientUnsupported,
)
from src.nextgen.acquisition.qbittorrent import Client as QbClient


class MetadataSourceConfigurationError(ValueError):
    reason_code = 'TORRENT_METADATA_CONFIGURATION_INVALID'
    def __init__(self):
        super().__init__('Configure qBittorrent credentials and download folder.')


class MetadataSourceUnavailable(RuntimeError):
    reason_code = 'TORRENT_METADATA_UNAVAILABLE'
    def __init__(self):
        super().__init__('qBittorrent could not provide torrent metadata.')


class MetadataSourceDenied(ValueError):
    reason_code = 'TORRENT_METADATA_DENIED'
    def __init__(self):
        super().__init__('qBittorrent rejected the metadata request.')


class MetadataClientUnsupported(MetadataSourceDenied):
    reason_code = 'TORRENT_METADATA_CLIENT_UNSUPPORTED'
    def __init__(self):
        ValueError.__init__(self, 'The batch requires a safely owned stopped torrent before older qBittorrent can export metadata.')


class MetadataSourceWaiting(RuntimeError):
    reason_code = 'TORRENT_METADATA_WAITING'
    def __init__(self, delay_ms=60000):
        self.delay_ms = delay_ms
        super().__init__('qBittorrent is still retrieving torrent metadata.')


def source_url(value):
    """Historical v7-v11 URL validation; never used to fetch current metadata."""
    try:
        if type(value) is not str or not value or len(value)>2048:raise ValueError()
        parsed=urllib.parse.urlsplit(value)
        authority=endpoint(urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'','','')))
        if (parsed.query or parsed.fragment or '?' in value or '#' in value or '%' in value
                or '\\' in value or not value.isascii() or any(ord(c)<=32 or ord(c)==127 for c in value)):
            raise ValueError()
        path=parsed.path.rstrip('/')
        if path and (not path.startswith('/')
                     or any(not re.fullmatch('[A-Za-z0-9_-]+',p)
                            for p in path[1:].split('/'))):
            raise ValueError()
        return authority+path
    except (ValueError, TypeError, AttributeError):
        raise MetadataSourceConfigurationError() from None


async def _qb_metadata(source, digest, configuration, cancelled, *,
                       secrets, client_factory, batch):
    """Only read-only, hash-bound qBittorrent metadata APIs, never a torrent add."""
    if cancelled.is_set():
        raise asyncio.CancelledError()
    if secrets is None:
        raise MetadataSourceConfigurationError()
    try:
        options = download_options(configuration)
        credentials = await blocking(secrets.qbittorrent_credentials)
        qb = client_factory(options, credentials)
        await blocking(qb.login)
        if cancelled.is_set():
            raise asyncio.CancelledError()
        if qb.metadata_strategy == 'fetch':
            result = await blocking(qb.fetch_metadata, source, digest, batch=batch)
            if result is None:
                raise MetadataSourceWaiting()
            raw = result[1]
        elif qb.metadata_strategy == 'guarded_export':
            # Export reads an already-stopped torrent without taking it over.
            # First-time older-client batch admission is a separate journaled
            # operation and must never be inferred from the presence of a tag.
            observed = await blocking(qb.inspect, digest)
            if observed is None or observed.state not in (
                    'pausedDL','pausedUP','stoppedDL','stoppedUP'):
                raise MetadataClientUnsupported()
            _,raw = await blocking(qb.export_metainfo, digest, batch=batch)
        else:
            # qB 4.2's torrent file list is NOT portable BEP3 infohash evidence.
            raise MetadataClientUnsupported()
        if cancelled.is_set():
            raise asyncio.CancelledError()
        return raw
    except DownloadConfigurationError:
        raise MetadataSourceConfigurationError() from None
    except ClientUnsupported:
        raise MetadataClientUnsupported() from None
    except ClientUnavailable:
        raise MetadataSourceUnavailable() from None
    except (ClientAuthenticationFailed,ClientInvalid):
        raise MetadataSourceDenied() from None


def make_reader(*, client_factory=QbClient, secrets=None):
    """Single-episode metadata reader. Older clients use PREPARE bootstrap."""
    async def read_metainfo(source, configuration, cancelled):
        if cancelled.is_set():
            raise asyncio.CancelledError()
        from src.nextgen.storage.acquisition import source_magnet
        magnet = await blocking(
            source_magnet,configuration.value('storage.database_path'),source)
        return await _qb_metadata(magnet, infohash(source.info_hash), configuration,
                                  cancelled,secrets=secrets,
                                  client_factory=client_factory,batch=False)
    return read_metainfo


def make_batch_reader(*, client_factory=QbClient, secrets=None):
    """Only a normalized hash is supplied to the batch verifier."""
    async def read_batch_metainfo(expected_hash, configuration, cancelled):
        digest = infohash(expected_hash)
        return await _qb_metadata(digest,digest,configuration,cancelled,
                                  secrets=secrets,client_factory=client_factory,
                                  batch=True)
    return read_batch_metainfo
