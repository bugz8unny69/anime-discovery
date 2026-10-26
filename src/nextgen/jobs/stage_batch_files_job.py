"""Copy every verified regular episode into staging; never move qB sources.

A single worker job serializes the publisher, commits exact receipts for
all episodes together, and marks the operation staged only once complete.
"""
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.cancellation import CancellationError
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.staging import Publisher, StagingReview, StagingUnavailable, StagingBusy
from src.nextgen.storage.batch_staging import BatchStagingJournal, persist_batch_staging
from src.nextgen.worker import blocking


KIND='STAGE_BATCH_FILES'
DEFINITION=HandlerDefinition(KIND,'Copy verified batch episodes into staging')


def _persist(db,claim,value):
    try:
        if (type(value) is not dict or
                set(value)!={'media_job_id','staging_job_id','receipts'}
                or value['staging_job_id']!=claim.job_id):
            raise StagingReview()
        return persist_batch_staging(
            db,claim,integer(value['media_job_id'],positive=True),value['receipts'])
    except (StagingReview,CancellationError,ValueError,TypeError) as exc:
        raise CompletionRejected(
            Outcome('review',getattr(exc,'reason_code','STAGING_REVIEW'))) from None


def registration(*,publisher_factory=Publisher,journal_factory=BatchStagingJournal):
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'media_job_id'} or context.claim.event_id is None:
                raise ValueError()
            media_job=integer(payload['media_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        def run():
            journal=journal_factory(context.configuration.value('storage.database_path'))
            publisher=publisher_factory(journal,context.claim,context.cancelled)
            with journal.lock(context.claim):
                count=journal.count(context.claim,media_job)
                receipts=[]
                for position in range(count):
                    index,episode,plan=journal.prepare_episode(
                        context.claim,media_job,position,context.configuration)
                    if plan.get('transfer')!='COPY':
                        raise StagingReview()
                    result=publisher.publish(plan)
                    journal.guard(context.claim)
                    receipts.append((index,result))
                return {'media_job_id':media_job,'staging_job_id':context.claim.job_id,
                        'receipts':tuple(receipts)}
        try:
            return Outcome(value=await blocking(run))
        except StagingBusy as exc:
            return Outcome('defer',exc.reason_code,delay_ms=1000)
        except (StagingUnavailable,OSError):
            return Outcome('retry','STAGING_UNAVAILABLE')
        except (StagingReview,CancellationError,MediaInvalid) as exc:
            return Outcome('review',exc.reason_code)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
