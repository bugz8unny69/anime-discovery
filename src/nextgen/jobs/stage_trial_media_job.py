"""Move verified viewing videos; Keep and library refresh remain separate."""
import logging

from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.acquisition.metadata import AcquisitionConflict, MetadataInvalid, SourceMissing
from src.nextgen.acquisition.settings import SizeEvidenceMissing, DownloadConfigurationError
from src.nextgen.acquisition.submission import ClientInvalid
from src.nextgen.acquisition.transfers import TransferConflict
from src.nextgen.async_io import blocking
from src.nextgen.cancellation import CancellationError
from src.nextgen.diagnostics import exception
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.staging import Publisher, StagingReview, StagingUnavailable, StagingBusy
from src.nextgen.storage.staging import Journal, persist

KIND='STAGE_TRIAL_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Move verified video into staging with episode metadata')
REVIEW=(StagingReview,MediaInvalid,AcquisitionConflict,MetadataInvalid,SourceMissing,
        SizeEvidenceMissing,DownloadConfigurationError,ClientInvalid,TransferConflict,CancellationError)


def _persist(db,claim,value):
    try:
        value=dict(value)
        refresh=value.pop('refresh',False)
        records=persist(db,claim,value)
        if refresh:
            from src.nextgen.jobs.refresh_jellyfin_job import enqueue
            enqueue(db,claim)
        return records
    except REVIEW as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration(*,publisher_factory=Publisher,journal_factory=Journal):
    async def execute(context):
        def failure(exc,kind,reason):
            exception(context.logger,'OPERATION_FAILED',exc,level=logging.WARNING,
                      reason_code=reason,component='worker',job_id=context.claim.job_id,
                      event_id=context.claim.event_id,attempt=context.claim.attempt)
            return Outcome(kind,reason)
        payload=context.data()
        try:
            if set(payload)!={'verification_job_id'} or context.claim.event_id is None:raise ValueError()
            verification=integer(payload['verification_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        def run():
            journal=journal_factory(context.configuration.value('storage.database_path'))
            publisher=publisher_factory(journal,context.claim,context.cancelled)
            with journal.lock(context.claim):
                plan=journal.prepare(context.claim,verification,context.configuration)
                receipts=publisher.publish(plan)
                journal.guard(context.claim)
                return {'verification_job_id':verification,'receipts':receipts,'refresh':bool(context.configuration.value('jellyfin.base_url'))}
        try:return Outcome(value=await blocking(run))
        except StagingBusy as exc:return Outcome('defer',exc.reason_code,delay_ms=1000)
        except FileExistsError as exc:return failure(exc,'review','STAGING_REVIEW')
        except (StagingUnavailable,OSError) as exc:return failure(exc,'retry','STAGING_UNAVAILABLE')
        except REVIEW as exc:return failure(exc,'review',exc.reason_code)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
