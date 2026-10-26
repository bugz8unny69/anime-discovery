"""Explicit batch-only qB adapter. Not installed in the worker.

Its sole mutation is a stopped add guarded by the journal's one-shot permit.
No file priority updates, start, or cleanup commands are offered here.
"""
import uuid

from src.nextgen.acquisition.metadata import parse_batch_metainfo
from src.nextgen.acquisition.qbittorrent import Client
from src.nextgen.acquisition.submission import ClientInvalid
from src.nextgen.storage.batch_submission_journal import (
    BatchSubmissionIntent, BatchSendPermit,
)


class BatchClient(Client):
    def add_batch_stopped(self,raw,intent,permit):
        if (not self._sid or self.major not in (4,5)
                or type(intent) is not BatchSubmissionIntent
                or type(permit) is not BatchSendPermit
                or self.options!=intent.options
                or self.major!=intent.api_major
                or intent.state!='UNCERTAIN'):
            raise ClientInvalid()
        try:
            inventory=parse_batch_metainfo(raw,intent.inventory.info_hash)
        except ValueError:
            raise ClientInvalid() from None
        if inventory!=intent.inventory:
            raise ClientInvalid()
        # This single method cannot resume, reprioritize or implicitly start.
        # The exact stopped, owned torrent must be reconciled on any failure.
        boundary='ad'+uuid.uuid4().hex
        while boundary.encode() in raw:
            boundary='ad'+uuid.uuid4().hex
        fields={
            'savepath':intent.options.download_root,
            'category':intent.options.category,
            'tags':'ad-'+intent.marker,
            'stopped' if self.major==5 else 'paused':'true',
            'autoTMM':'false','useDownloadPath':'false',
            'skip_checking':'false','contentLayout':'Original',
        }
        chunks=[]
        for key,value in fields.items():
            chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+
                           '"\r\n\r\n'+value+'\r\n').encode())
        chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; '
                       'name="torrents"; filename="source.torrent"\r\n'
                       'Content-Type: application/x-bittorrent\r\n\r\n').encode()
                      +raw+b'\r\n')
        chunks.append(('--'+boundary+'--\r\n').encode())
        permit.take(intent)
        self._request(
            'torrents/add',
            body=b''.join(chunks),
            content_type='multipart/form-data; boundary='+boundary,
            limit=4096)

    def apply_probe_selection(self,intent,fingerprint,permit,action):
        """Mutate only E01 probe priorities; one permit per API command."""
        from src.nextgen.acquisition.transfers import TransferPermit, TransferConflict
        from src.nextgen.batch.probe_transfer import (
            verify_probe_snapshot, selection_fingerprint,
        )
        if (not self._sid or self.major not in (4,5)
                or type(intent) is not BatchSubmissionIntent
                or type(permit) is not TransferPermit
                or self.options!=intent.options
                or action not in ('skip','wanted')):
            raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.inventory.info_hash)
        if snapshot is None:raise TransferConflict()
        verify_probe_snapshot(intent,snapshot,require_stopped=True)
        if selection_fingerprint(intent,snapshot.piece_size)!=fingerprint:
            raise TransferConflict()
        probe=intent.candidate.probe_index
        if action=='skip':
            indices=[i for i in range(len(snapshot.priorities)) if i!=probe]
            priority=0
        else:
            indices=[probe]
            priority=1
        permit.take(fingerprint,action)
        if indices:
            self._request('torrents/filePrio',form={
                'hash':intent.inventory.info_hash,
                'id':'|'.join(map(str,indices)),
                'priority':priority,
            },limit=4096)

    def start_probe(self,intent,fingerprint,permit):
        """Start only when E01 is the exact sole wanted file."""
        from src.nextgen.acquisition.transfers import TransferPermit, TransferConflict
        from src.nextgen.batch.probe_transfer import (
            verify_probe_snapshot, exact_probe_selection, selection_fingerprint,
        )
        if (not self._sid or self.major not in (4,5)
                or type(intent) is not BatchSubmissionIntent
                or type(permit) is not TransferPermit
                or self.options!=intent.options):
            raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.inventory.info_hash)
        if snapshot is None:raise TransferConflict()
        verify_probe_snapshot(intent,snapshot,require_stopped=True)
        if (selection_fingerprint(intent,snapshot.piece_size)!=fingerprint
                or not exact_probe_selection(intent,snapshot)):
            raise TransferConflict()
        permit.take(fingerprint,'start')
        self._request(
            'torrents/start' if self.major==5 else 'torrents/resume',
            form={'hashes':intent.inventory.info_hash},limit=4096)

    def apply_audio_verified_unlock(self,intent,media,unlock,permit):
        """Enable only other provider-approved trial files after real E01 proof."""
        from src.nextgen.acquisition.media import VerifiedMedia
        from src.nextgen.acquisition.transfers import TransferPermit, TransferConflict
        from src.nextgen.batch.unlock import (
            BatchUnlockIntent, plan_verified_unlock, validate_unlock_snapshot,
        )
        if (not self._sid or self.major not in (4,5)
                or type(intent) is not BatchSubmissionIntent
                or type(media) is not VerifiedMedia
                or type(unlock) is not BatchUnlockIntent
                or type(permit) is not TransferPermit
                or self.options!=intent.options):
            raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.inventory.info_hash)
        if snapshot is None:raise TransferConflict()
        required=plan_verified_unlock(
            intent,snapshot,media,unlock.verification_job_id)
        if required!=unlock:raise TransferConflict()
        wanted=[i for i,p in enumerate(unlock.priorities)
                if p==1 and i!=intent.candidate.probe_index]
        if not wanted:raise TransferConflict()
        permit.take(unlock.fingerprint,'unlock')
        self._request('torrents/filePrio',form={
            'hash':intent.inventory.info_hash,
            'id':'|'.join(map(str,wanted)),
            'priority':1,
        },limit=4096)

    def start_audio_verified_batch(self,intent,unlock,permit):
        """Start a proven exact expanded selection, never an unverified pack."""
        from src.nextgen.acquisition.transfers import TransferPermit, TransferConflict
        from src.nextgen.batch.unlock import (
            BatchUnlockIntent, validate_unlock_snapshot, exact_unlock_selection,
        )
        if (not self._sid or self.major not in (4,5)
                or type(intent) is not BatchSubmissionIntent
                or type(unlock) is not BatchUnlockIntent
                or type(permit) is not TransferPermit
                or self.options!=intent.options
                or unlock.plan_id!=intent.candidate.plan_id):
            raise ClientInvalid()
        snapshot=self.inspect_transfer(intent.inventory.info_hash)
        if snapshot is None:raise TransferConflict()
        validate_unlock_snapshot(intent,snapshot,stopped=True)
        if not exact_unlock_selection(unlock,snapshot):raise TransferConflict()
        permit.take(unlock.fingerprint,'start')
        self._request(
            'torrents/start' if self.major==5 else 'torrents/resume',
            form={'hashes':intent.inventory.info_hash},limit=4096)
