"""Read-only selected-video verification; staging remains a separate component."""
from functools import partial
from src.nextgen.acquisition.media import verify_file, MediaInvalid, MediaUnavailable, ProbeUnavailable
from src.nextgen.acquisition.metadata import AcquisitionConflict, MetadataInvalid, SourceMissing
from src.nextgen.acquisition.settings import SizeEvidenceMissing, DownloadConfigurationError
from src.nextgen.acquisition.submission import ClientInvalid
from src.nextgen.acquisition.transfers import TransferConflict
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.media_verification import load, persist
from src.nextgen.worker import blocking

KIND='VERIFY_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Verify downloaded video and required audio')
REVIEW=(MediaInvalid,AcquisitionConflict,MetadataInvalid,SourceMissing,SizeEvidenceMissing,
        DownloadConfigurationError,ClientInvalid,TransferConflict)


def _persist(db,claim,value):
    try:persist(db,claim,value)
    except REVIEW as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration(*,verify=verify_file,load_input=load):
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'preparation_job_id','download_job_id'} or context.claim.event_id is None:raise ValueError()
            preparation=integer(payload['preparation_job_id'],positive=True)
            download=integer(payload['download_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            intent,record=await blocking(load_input,context.configuration.value('storage.database_path'),
                                        context.claim,preparation,download)
            work=partial(verify,intent,record,download,context.cancelled,protected_roots=(
                context.configuration.value('storage.trial_root'),context.configuration.value('storage.keep_root')))
            value=await blocking(work)
            return Outcome(value=value)
        except MediaUnavailable as exc:return Outcome('retry',exc.reason_code)
        except ProbeUnavailable as exc:return Outcome('review',exc.reason_code)
        except REVIEW as exc:return Outcome('review',exc.reason_code)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
