"""Trusted batch-release provider composition, separate from single episodes.

This verifies immutable metadata and AniDB/Anime-Lists/TVDB episode facts;
it never submits a torrent or makes a trial/Keep decision.
"""
from dataclasses import dataclass, field
import inspect

from src.nextgen.acquisition.metadata import BatchInventory, infohash, parse_batch_metainfo
from src.nextgen.batch.recognition import release_scope_hint
from src.nextgen.batch.verification import VerifiedBatch, verify_batch_files
from src.nextgen.providers.errors import ProviderAuthenticationFailed
from src.nextgen.providers.http import Clients, Credentials, Options, json_object
from src.nextgen.providers.identity import ClientPool, delivery_title
from src.nextgen.release_contracts import ReleaseInput, ReleaseNotReady
from src.nextgen.worker import blocking


@dataclass(frozen=True)
class BatchVerificationCompletion:
    source: ReleaseInput = field(repr=False)
    inventory: BatchInventory = field(repr=False)
    verified: VerifiedBatch

    def __post_init__(self):
        if type(self.source) is not ReleaseInput or type(self.inventory) is not BatchInventory:
            raise ValueError('Typed release and batch metadata required')
        if type(self.verified) is not VerifiedBatch:
            raise ValueError('Batch provider proof required')
        if (self.source.anidb_id,self.source.tvdb_series_id) != (
                self.verified.anidb_id,self.verified.tvdb_series_id):
            raise ValueError('Provider proof belongs to a different series')
        if (self.inventory.info_hash,self.inventory.info_sha256) != (
                self.verified.info_hash,self.verified.info_sha256):
            raise ValueError('Provider proof belongs to a different torrent')


def make_batch_verifier(options, credentials, read_batch_metainfo, *,
                        client_pool=None, client_factory=Clients):
    """Return async batch verifier callable suitable for the release job.

    The configured metainfo reader accepts ONLY a 40-character infohash,
    never an untrusted URL. Client factory and credentials are service-owned.
    """
    if ((type(options) is not Options and not callable(options))
            or not callable(credentials)
            or not inspect.iscoroutinefunction(read_batch_metainfo)):
        raise ValueError('Incomplete trusted batch provider composition')
    pool=client_pool or ClientPool(client_factory)

    async def call(source,configuration,cancelled):
        if type(source) is not ReleaseInput:
            raise ValueError('Release source required')
        if cancelled.is_set():
            raise ReleaseNotReady()
        hint=release_scope_hint(delivery_title(source))
        if hint.kind not in ('season_pack','mixed_pack') or not hint.season_hint:
            raise ReleaseNotReady('RELEASE_TYPE_UNSUPPORTED')
        document=json_object(source.raw_body)
        try:
            digest=infohash(document.get('torrent_infohash'))
        except ValueError:
            raise ReleaseNotReady('RELEASE_UNRESOLVED') from None
        raw=await read_batch_metainfo(digest,configuration,cancelled)
        inventory=await blocking(parse_batch_metainfo,raw,digest)
        actual=options(configuration) if callable(options) else options
        secret=credentials()
        if type(secret) is not Credentials:
            raise ProviderAuthenticationFailed()
        client=pool.get(configuration.value('storage.database_path'),actual)
        verified=await blocking(
            verify_batch_files,inventory,client=client,credentials=secret,
            anidb_id=source.anidb_id,tvdb_series_id=source.tvdb_series_id,
            season=hint.season_hint,cancelled=cancelled)
        if cancelled.is_set():
            raise ReleaseNotReady()
        return BatchVerificationCompletion(source,inventory,verified)
    return call
