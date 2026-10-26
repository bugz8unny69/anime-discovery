"""Serialize each batch episode's existing crash-safe Sonarr import flow."""
from src.nextgen.keep_service import Service as SingleService
from src.nextgen.storage.batch_keep_imports import (
    BatchKeepJournal, batch_keep_file_indices,
)
from src.nextgen.storage.staging import Journal as StageJournal
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction


class BatchKeepService:
    def __init__(self,configuration,secrets,*,client_factory=None):
        self.configuration=configuration
        self.secrets=secrets
        self.client_factory=client_factory
        self.queue=JobQueue(configuration.value('storage.database_path'))

    def run(self,claim,target,cancelled):
        with StageJournal(self.queue.database).lock(claim):
            with self.queue.connection() as db,transaction(db):
                self.queue._owns(db,claim,self.queue.now())
                indices=batch_keep_file_indices(db,claim,target)
            for index in indices:
                factory=lambda database,idx=index:BatchKeepJournal(
                    database,file_index=idx)
                kwargs={'journal_factory':factory}
                if self.client_factory is not None:
                    kwargs['client_factory']=self.client_factory
                service=SingleService(self.configuration,self.secrets,**kwargs)
                # The outer lock applies to the entire batch; invoking _run
                # avoids a second competing per-job I/O lock.
                if not service._run(claim,target,cancelled):
                    return False
            return True
