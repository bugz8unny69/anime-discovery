"""Clean exactly owned batch torrent/files after completed Keep or Reject."""
import inspect

from src.nextgen.acquisition.metadata import parse_batch_metainfo, MetadataInvalid
from src.nextgen.acquisition.submission import (
    ClientUnavailable, ClientInvalid, ClientAuthenticationFailed, ClientUnsupported,
)
from src.nextgen.acquisition.metainfo_source import (
    MetadataSourceWaiting, MetadataSourceUnavailable,
    MetadataSourceConfigurationError, MetadataSourceDenied,
)
from src.nextgen.batch.decision_cleanup import KIND, Service
from src.nextgen.cancellation import CancellationError
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.batch_decision_cleanup import BatchDecisionJournal
from src.nextgen.worker import blocking


DEFINITION=HandlerDefinition(KIND,'Remove decided owned batch torrent and exact source files')


def _persist(db,claim,value):
    row=db.execute(
        "SELECT phase FROM batch_download_cleanups WHERE cleanup_job_id=?",
        (claim.job_id,)).fetchone()
    if row!=('COMPLETE',):
        raise CompletionRejected(Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW'))


def registration(read_batch_metainfo,secrets,*,service_factory=Service,
                 journal_factory=BatchDecisionJournal):
    if not inspect.iscoroutinefunction(read_batch_metainfo):
        raise ValueError('Trusted asynchronous metadata reader required')

    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'decision_job_id'}:
                raise ValueError()
            decision=integer(payload['decision_job_id'],positive=True)
        except (TypeError,ValueError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        journal=journal_factory(
            context.configuration.value('storage.database_path'))
        try:
            digest=await blocking(
                journal.source_hash,context.claim,decision)
            raw=await read_batch_metainfo(
                digest,context.configuration,context.cancelled)
            inventory=await blocking(parse_batch_metainfo,raw,digest)
            complete=await blocking(
                service_factory(context.configuration,secrets).run,
                context.claim,decision,inventory,context.cancelled)
            return Outcome() if complete else Outcome(
                'defer','DECISION_DOWNLOAD_CLEANUP_WAITING',delay_ms=30000)
        except MetadataSourceWaiting as exc:
            return Outcome('defer',exc.reason_code,delay_ms=exc.delay_ms)
        except MetadataSourceUnavailable as exc:
            return Outcome('retry',exc.reason_code)
        except (MetadataSourceConfigurationError,MetadataSourceDenied) as exc:
            return Outcome('review',exc.reason_code)
        except ClientUnavailable:
            return Outcome('retry','DOWNLOAD_CLIENT_UNAVAILABLE')
        except (CancellationError,MetadataInvalid,ClientInvalid,
                ClientAuthenticationFailed,ClientUnsupported,KeyError,
                ValueError,TypeError):
            return Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW')
        except OSError:
            return Outcome('retry','DOWNLOAD_CLIENT_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
