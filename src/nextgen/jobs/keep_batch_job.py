"""Whole-pack Keep: reconcile each independently staged episode with Sonarr."""
from functools import partial
import time

from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.batch_keep_imports import BatchKeepJournal, batch_publications
from src.nextgen.keep_service import Service
from src.nextgen.keep_selection import KeepSelectionInvalid
from src.nextgen.sonarr import KeepReview, KeepUnavailable
from src.nextgen.staging import StagingReview, StagingBusy
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.history import job_attempt, append_job_history
from src.nextgen.storage.cancellation import operation

KIND='KEEP_BATCH'
DEFINITION=HandlerDefinition(KIND,'Keep verified batch episodes in the permanent library')


def _persist(db,claim,value):
    if type(value) is not dict or set(value)!={'refresh'}:
        raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW'))
    row=db.execute(
        "SELECT target_job_id,operation_id FROM management_actions "
        "WHERE job_id=? AND action='KEEP'",(claim.job_id,)).fetchone()
    if row is None or operation(db,row[0])[:2]!=(row[1],'STAGED'):
        raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW'))
    try:staged=batch_publications(db,row[1])
    except KeepReview:
        raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW')) from None
    if db.execute(
        'SELECT file_index,phase FROM batch_keep_imports '
        'WHERE job_id=? ORDER BY file_index',(claim.job_id,)).fetchall()!=[
        (item[1],'COMPLETE') for item in staged]:
        raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW'))
    if value['refresh']:
        from src.nextgen.jobs.refresh_jellyfin_job import enqueue
        enqueue(db,claim)
    return (append_job_history(
        db,job_id=claim.job_id,event_code='KEEP_COMPLETED',
        reason_code='KEEP_COMPLETE',component='worker',
        occurred_at_ms=time.time_ns()//1000000,
        details={'attempt':job_attempt(db,claim.job_id)}),)


def registration(secrets,*,service_factory=Service):
    async def execute(context):
        actions=ManagementActions(context.configuration.value('storage.database_path'))
        try:target=await blocking(actions.bind,context.claim,'KEEP')
        except (ActionUnavailable,ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            def read():
                with actions.queue.connection() as db:
                    return tuple(row[1] for row in batch_publications(
                        db,operation(db,target)[0]))
            file_indices=await blocking(read)
            for index in file_indices:
                factory=partial(BatchKeepJournal,file_index=index)
                complete=await blocking(
                    service_factory(context.configuration,secrets,
                                    journal_factory=factory).run,
                    context.claim,target,context.cancelled)
                if not complete:
                    return Outcome('defer','KEEP_IMPORT_WAITING',delay_ms=30000)
            return Outcome(value={
                'refresh':bool(context.configuration.value('jellyfin.base_url'))})
        except StagingBusy:
            return Outcome('defer','KEEP_IMPORT_WAITING',delay_ms=1000)
        except KeepUnavailable:
            return Outcome('retry','KEEP_SERVICE_UNAVAILABLE')
        except (KeepReview,KeepSelectionInvalid,StagingReview,MediaInvalid,
                ValueError,KeyError,TypeError):
            return Outcome('review','KEEP_IMPORT_REVIEW')
        except (OSError,PermissionError):
            return Outcome('retry','KEEP_SERVICE_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
