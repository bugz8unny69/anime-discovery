"""Cleanup kept batch viewing copies after independently confirmed Sonarr imports."""
from src.nextgen.batch.post_keep_cleanup import (
    KIND, Service,
)
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.sonarr import KeepReview, KeepUnavailable
from src.nextgen.staging import StagingReview, StagingBusy
from src.nextgen.cancellation import CancellationError


DEFINITION=HandlerDefinition(KIND,'Remove confirmed kept batch staging copies')


def _persist(db,claim,value):
    from src.nextgen.batch.decision_cleanup import enqueue
    if db.execute(
        "SELECT phase FROM batch_stage_cleanups WHERE job_id=?",
        (claim.job_id,)).fetchone()!=('COMPLETE',):
        raise CompletionRejected(Outcome('review','POST_KEEP_CLEANUP_REVIEW'))
    enqueue(db,claim,action='KEEP')


def registration(secrets,*,service_factory=Service):
    from src.nextgen.worker import blocking

    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'keep_job_id'}:raise ValueError()
            keep=integer(payload['keep_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            finished=await blocking(
                service_factory(context.configuration,secrets).run,
                context.claim,keep,context.cancelled)
            return Outcome() if finished else Outcome(
                'defer','POST_KEEP_CLEANUP_WAITING',delay_ms=30000)
        except StagingBusy:
            return Outcome('defer','STAGING_BUSY',delay_ms=1000)
        except KeepUnavailable:
            return Outcome('retry','KEEP_SERVICE_UNAVAILABLE')
        except (KeepReview,StagingReview,CancellationError,KeyError,TypeError,ValueError):
            return Outcome('review','POST_KEEP_CLEANUP_REVIEW')
        except OSError:
            return Outcome('retry','STAGING_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
