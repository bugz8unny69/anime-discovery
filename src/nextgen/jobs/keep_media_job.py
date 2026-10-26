"""Import one staged episode through Sonarr using verified TVDB placement."""
import time
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import Outcome, Registration, CompletionRejected
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.keep_service import Service
from src.nextgen.batch.keep_service import BatchKeepService
from src.nextgen.storage.batch_keep_imports import is_batch_staged
from src.nextgen.keep_selection import KeepSelectionInvalid
from src.nextgen.sonarr import KeepReview, KeepUnavailable
from src.nextgen.staging import StagingReview, StagingBusy
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.history import job_attempt, append_job_history

KIND='KEEP_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Keep staged video in the permanent library')


def _persist(db,claim,value):
    single=db.execute(
        'SELECT phase FROM keep_imports WHERE job_id=?',
        (claim.job_id,)).fetchone()
    batch=db.execute(
        "SELECT count(*),sum(CASE WHEN phase='COMPLETE' THEN 1 ELSE 0 END),"
        "count(DISTINCT plan_id) FROM batch_keep_imports WHERE job_id=?",
        (claim.job_id,)).fetchone()
    if single==('COMPLETE',):
        from src.nextgen.post_keep_cleanup import enqueue as enqueue_cleanup
        enqueue_cleanup(db,claim)
    elif batch[0]>0 and batch[0]==batch[1] and batch[2]==1:
        target=db.execute(
            "SELECT target_job_id FROM management_actions "
            "WHERE job_id=? AND action='KEEP'",(claim.job_id,)).fetchone()
        if target is None or not is_batch_staged(db,target[0]):
            raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW'))
        # Batch staging cleanup has a separate per-file ownership journal.
        # No single-episode source deletion is authorized by this completion.
    else:
        raise CompletionRejected(Outcome('review','KEEP_IMPORT_REVIEW'))
    if value and value.get('refresh'):
        from src.nextgen.jobs.refresh_jellyfin_job import enqueue
        enqueue(db,claim)
    if single==('COMPLETE',) and value and value.get('shoko'):
        from src.nextgen.jobs.enrich_shoko_job import enqueue as enqueue_shoko
        enqueue_shoko(db,claim)
    return (append_job_history(db,job_id=claim.job_id,event_code='KEEP_COMPLETED',reason_code='KEEP_COMPLETE',
        component='worker',occurred_at_ms=time.time_ns()//1000000,details={'attempt':job_attempt(db,claim.job_id)}),)


def registration(secrets=None,*,service_factory=Service,
                 batch_service_factory=BatchKeepService):
    async def execute(context):
        actions=ManagementActions(context.configuration.value('storage.database_path'))
        try:await blocking(actions.bind,context.claim,'KEEP')
        except (ActionUnavailable,ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            with actions.queue.connection() as db:
                batch=is_batch_staged(db,context.data()['target_job_id'])
            service=(batch_service_factory if batch else service_factory)(
                context.configuration,secrets)
            complete=await blocking(service.run,context.claim,
                                   context.data()['target_job_id'],context.cancelled)
            return Outcome(value={'refresh':bool(context.configuration.value('jellyfin.base_url')),'shoko':bool(context.configuration.value('shoko.base_url'))}) if complete else Outcome('defer','KEEP_IMPORT_WAITING',delay_ms=30000)
        except StagingBusy:return Outcome('defer','KEEP_IMPORT_WAITING',delay_ms=30000)
        except KeepUnavailable:return Outcome('retry','KEEP_SERVICE_UNAVAILABLE')
        except KeepReview as exc:return Outcome('review',exc.reason_code)
        except (KeepSelectionInvalid,StagingReview,MediaInvalid,ValueError,KeyError,TypeError):return Outcome('review','KEEP_IMPORT_REVIEW')
        except PermissionError:return Outcome('review','KEEP_IMPORT_REVIEW')
        except OSError:return Outcome('retry','KEEP_SERVICE_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
