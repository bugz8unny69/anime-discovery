"""Owned batch torrent deletion only after all Keep/Reject work is durable."""
import inspect

from src.nextgen.acquisition.metadata import (
    parse_batch_metainfo, MetadataInvalid, AcquisitionConflict,
)
from src.nextgen.acquisition.submission import (
    ClientUnavailable, ClientInvalid, ClientAuthenticationFailed, ClientUnsupported,
)
from src.nextgen.acquisition.metainfo_source import (
    MetadataSourceWaiting, MetadataSourceUnavailable,
    MetadataSourceConfigurationError, MetadataSourceDenied,
)
from src.nextgen.async_io import blocking
from src.nextgen.batch_decision_cleanup import BatchDecisionCleanup
from src.nextgen.cancellation import CancellationError
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.sqlite import enqueue_job

KIND='CLEANUP_BATCH_DOWNLOAD'
DEFINITION=HandlerDefinition(KIND,'Reconcile and remove owned completed batch torrent')


def enqueue(db,claim):
    return enqueue_job(
        db,kind=KIND,component='worker',
        payload={'decision_job_id':claim.job_id},
        event_id=claim.event_id,created_by_job_id=claim.job_id)


def _persist(db,claim,value):
    if type(value) is not dict or set(value)!={'decision_job_id'}:
        raise CompletionRejected(Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW'))
    decision=integer(value['decision_job_id'],positive=True)
    row=db.execute(
        "SELECT c.phase,j.state,j.kind,k.created_by_job_id,k.event_id "
        "FROM batch_download_cleanup c "
        "JOIN jobs j ON j.job_id=c.decision_job_id "
        "JOIN jobs k ON k.job_id=? "
        "WHERE c.decision_job_id=?",
        (claim.job_id,decision)).fetchone()
    if (row is None or row[0]!='COMPLETE' or row[1]!='DONE'
            or row[2] not in ('KEEP_BATCH','REJECT_BATCH')
            or row[3]!=decision or row[4]!=claim.event_id):
        raise CompletionRejected(Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW'))


def registration(read_batch_metainfo,secrets,*,
                 service_factory=BatchDecisionCleanup):
    if not inspect.iscoroutinefunction(read_batch_metainfo):
        raise ValueError('Trusted async hash-only batch metainfo reader required')

    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'decision_job_id'}:
                raise ValueError()
            decision=integer(payload['decision_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        service=service_factory(context.configuration,secrets)
        try:
            digest=await blocking(service.source_hash,context.claim,decision)
            raw=await read_batch_metainfo(
                digest,context.configuration,context.cancelled)
            inventory=await blocking(parse_batch_metainfo,raw,digest)
            completed=await blocking(
                service.run,context.claim,decision,inventory,context.cancelled)
            return (Outcome(value={'decision_job_id':decision}) if completed
                    else Outcome('defer','DECISION_DOWNLOAD_CLEANUP_WAITING',
                                 delay_ms=30000))
        except MetadataSourceWaiting as exc:
            return Outcome('defer',exc.reason_code,delay_ms=exc.delay_ms)
        except MetadataSourceUnavailable as exc:
            return Outcome('retry',exc.reason_code)
        except (MetadataSourceConfigurationError,MetadataSourceDenied) as exc:
            return Outcome('review',exc.reason_code)
        except (ClientUnavailable,):
            return Outcome('retry','DECISION_DOWNLOAD_CLEANUP_UNAVAILABLE')
        except (CancellationError,ClientInvalid,ClientAuthenticationFailed,
                ClientUnsupported,MetadataInvalid,AcquisitionConflict):
            return Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW')
        except OSError:
            return Outcome('retry','DECISION_DOWNLOAD_CLEANUP_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
