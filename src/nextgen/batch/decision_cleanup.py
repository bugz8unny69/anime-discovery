"""Explicit Keep/Reject batch source cleanup with one-shot qB commands.

No unbounded folder removal, no direct HTTP torrent IDs, no retry of an
uncertain destructive send. This only consumes immutable decision ownership.
"""
from src.nextgen.acquisition.cleanup import CleanupPermit, FileCleanup
from src.nextgen.acquisition.submission import ClientUnavailable
from src.nextgen.acquisition.transfers import STOPPED, CHECKING
from src.nextgen.batch.owned_cleanup import owned_batch_observation
from src.nextgen.batch.qb_client import BatchClient
from src.nextgen.cancellation import CancellationError
from src.nextgen.storage.batch_decision_cleanup import (
    KIND, enqueue, BatchDecisionJournal,
)
from src.nextgen.storage.staging import Journal as StageJournal


class Service:
    def __init__(self,configuration,secrets,*,client_factory=BatchClient,
                 files_factory=FileCleanup,journal_factory=BatchDecisionJournal):
        self.configuration,self.secrets=configuration,secrets
        self.client_factory,self.files_factory=client_factory,files_factory
        self.journal=journal_factory(configuration.value('storage.database_path'))

    def run(self,claim,decision_job_id,inventory,cancelled):
        journal=self.journal

        def allowed():
            if cancelled.is_set():raise CancellationError()

        with StageJournal(journal.queue.database).lock(claim):
            intent,record=journal.load(claim,decision_job_id,inventory)
            if record.phase=='COMPLETE':return True
            client=self.client_factory(
                intent.options,self.secrets.qbittorrent_credentials())
            client.login()
            cleaner=self.files_factory(
                intent.file_cleanup_source(),
                (self.configuration.value('storage.trial_root'),
                 self.configuration.value('storage.keep_root')))

            def inspect():
                allowed()
                return client.inspect(intent.inventory.info_hash)

            current=inspect()
            if record.phase in ('PREPARED','STOP_UNCERTAIN'):
                if current is None:raise CancellationError()
                observation=owned_batch_observation(intent,current)
                if observation.state in CHECKING:return False
                if observation.state not in STOPPED:
                    if record.phase=='STOP_UNCERTAIN':
                        return False  # Never rearm an uncertain stop.
                    record,_=journal.advance(
                        claim,decision_job_id,intent,'PREPARED','STOP_UNCERTAIN')
                    allowed()
                    journal.guard_send(
                        claim,decision_job_id,intent,'STOP_UNCERTAIN')
                    try:
                        client.cleanup_owned_batch(
                            intent,CleanupPermit(intent.fingerprint,'stop'),'stop')
                    except ClientUnavailable:
                        return False
                    current=inspect()
                    if current is None:return False
                    observation=owned_batch_observation(intent,current)
                    if observation.state not in STOPPED:return False
                # Preserve a frozen inode receipt *before* removing the
                # external torrent. Unknown extra files abort cleanup.
                allowed()
                files=cleaner.capture()
                prior=record.phase
                record,_=journal.advance(
                    claim,decision_job_id,intent,prior,'REMOVE_UNCERTAIN',
                    files=files)
                allowed()
                journal.guard_send(
                    claim,decision_job_id,intent,'REMOVE_UNCERTAIN')
                try:
                    client.cleanup_owned_batch(
                        intent,CleanupPermit(intent.fingerprint,'remove'),'remove')
                except ClientUnavailable:
                    return False
                current=inspect()

            if record.phase=='REMOVE_UNCERTAIN':
                if current is not None:
                    owned_batch_observation(intent,current)
                    # An uncertain remove may have committed remotely.
                    # Observing it still present does NOT authorize resend.
                    return False
                record,_=journal.advance(
                    claim,decision_job_id,intent,'REMOVE_UNCERTAIN','FILES')

            if record.phase=='FILES':
                def guard():
                    allowed()
                    journal.guard(claim,decision_job_id,intent)
                    # Absence must hold before every local unlink. A fresh
                    # torrent with the same hash may not be silently cleaned.
                    if inspect() is not None:raise CancellationError()
                guard()
                cleaner.remove(record.files,guard=guard)
                guard()
                record,_=journal.advance(
                    claim,decision_job_id,intent,'FILES','COMPLETE')
            return record.phase=='COMPLETE'
