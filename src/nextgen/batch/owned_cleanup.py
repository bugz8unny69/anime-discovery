"""Exact immutable ownership receipt for batch qBittorrent cleanup.

This intent is valid only for destructive cleanup after an explicit
completed Keep/Reject decision (or separately reconciled cancellation).
It must never be accepted by the acquisition submission/start paths.
"""
from dataclasses import dataclass,field
from types import SimpleNamespace
import hashlib
import json
from pathlib import PurePosixPath

from src.nextgen.acquisition.metadata import BatchInventory
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.acquisition.submission import Observation
from src.nextgen.acquisition.transfers import STOPPED
from src.nextgen.cancellation import CancellationError


@dataclass(frozen=True)
class BatchOwnedCleanupIntent:
    plan_id: int
    inventory: BatchInventory = field(repr=False)
    options: DownloadOptions = field(repr=False)
    marker: str = field(repr=False)
    fingerprint: str

    def __post_init__(self):
        if (type(self.plan_id) is not int or self.plan_id<=0
                or type(self.inventory) is not BatchInventory
                or type(self.options) is not DownloadOptions
                or type(self.marker) is not str or len(self.marker)!=32
                or any(x not in '0123456789abcdef' for x in self.marker)
                or self.options.download_root.rsplit('/',1)[-1]!='ad-'+self.marker
                or type(self.fingerprint) is not str or len(self.fingerprint)!=64
                or self.fingerprint!=cleanup_fingerprint(
                    self.plan_id,self.inventory,self.options,self.marker)):
            raise CancellationError()

    def file_cleanup_source(self):
        """Shape consumed by the existing fd-relative exact FileCleanup."""
        manifest=SimpleNamespace(files=self.inventory.files)
        plan=SimpleNamespace(marker=self.marker,manifest=manifest)
        return SimpleNamespace(plan=plan,options=self.options)


def cleanup_fingerprint(plan_id,inventory,options,marker):
    if type(inventory) is not BatchInventory or type(options) is not DownloadOptions:
        raise CancellationError()
    return hashlib.sha256(json.dumps({
        'scope':'explicit_batch_decision_cleanup',
        'plan':plan_id,'info_hash':inventory.info_hash,
        'info_sha256':inventory.info_sha256,'owner':marker,
        'download_root':options.download_root,'category':options.category,
        'base_url':options.base_url,'api_timeout':options.timeout_seconds,
        'files':[(f.index,f.path,f.size) for f in inventory.files],
    },sort_keys=True,separators=(',',':')).encode()).hexdigest()


def owned_batch_observation(intent,observation,*,stopped=False):
    if type(intent) is not BatchOwnedCleanupIntent or type(observation) is not Observation:
        raise CancellationError()
    if (observation.info_hash!=intent.inventory.info_hash
            or observation.files!=intent.inventory.files
            or observation.save_path.rstrip('/')!=intent.options.download_root.rstrip('/')
            or observation.category!=intent.options.category
            or observation.auto_tmm is not False
            or 'ad-'+intent.marker not in observation.tags
            or any(t.startswith('ad-') and t!='ad-'+intent.marker
                   for t in observation.tags)):
        raise CancellationError()
    if stopped and observation.state not in STOPPED:raise CancellationError()
    return observation
