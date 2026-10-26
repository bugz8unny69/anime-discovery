"""Verify every selected batch video from actual bytes and JP+EN ffprobe.

Proofs for every selected episode are persisted together in the job's
fenced completion transaction; a partial result is never published.
"""
import inspect

from src.nextgen.acquisition.metadata import parse_batch_metainfo, AcquisitionConflict, MetadataInvalid
from src.nextgen.acquisition.media import MediaInvalid, MediaUnavailable, ProbeUnavailable, VerifiedMedia
from src.nextgen.acquisition.metainfo_source import (
    MetadataSourceWaiting, MetadataSourceUnavailable,
    MetadataSourceConfigurationError, MetadataSourceDenied,
)
from src.nextgen.batch.verified_files import verify_selected_batch_episode
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration, Successor
from src.nextgen.storage.batch_files_source import BatchFilesSource
from src.nextgen.storage.batch_verified_files import persist_batch_file_proof
from src.nextgen.worker import blocking


KIND='VERIFY_BATCH_FILES'
DEFINITION=HandlerDefinition(KIND,'Verify each selected batch video and its audio')


def _persist(db,claim,value):
    if (type(value) is not dict or set(value)!={'unlock_job_id','files','verification_job_id'}
            or type(value['files']) is not tuple):
        raise CompletionRejected(Outcome('review','MEDIA_VERIFICATION_INVALID'))
    try:
        if value['verification_job_id']!=claim.job_id:raise MediaInvalid()
        unlock=integer(value['unlock_job_id'],positive=True)
        row=db.execute(
            "SELECT u.plan_id,s.reservation_job_id,j.event_id,j.state "
            "FROM batch_torrent_unlocks u "
            "JOIN batch_torrent_submissions s USING(plan_id) "
            "JOIN jobs j ON j.job_id=u.unlock_job_id "
            "WHERE u.unlock_job_id=? AND u.phase='COMPLETE'",
            (unlock,)).fetchone()
        if row is None or row[2:]!=(claim.event_id,'DONE'):
            raise MediaInvalid()
        files=db.execute(
            "SELECT file_index,tvdb_episode FROM batch_trial_files "
            "WHERE plan_id=? ORDER BY tvdb_episode",(row[0],)).fetchall()
        if tuple((i,e) for i,e,_ in value['files'])!=tuple(files):
            raise MediaInvalid()
        from time import time_ns
        now=time_ns()//1000000
        for index,episode,media in value['files']:
            if (type(media) is not VerifiedMedia
                    or media.download_job_id!=unlock
                    or media.preparation_job_id!=row[1]
                    or media.plan_id!=row[0]):
                raise MediaInvalid()
            persist_batch_file_proof(
                db,claim,media,file_index=index,tvdb_episode=episode,now_ms=now)
    except (MediaInvalid,AcquisitionConflict,ValueError,TypeError) as exc:
        raise CompletionRejected(Outcome('review',getattr(exc,'reason_code','MEDIA_VERIFICATION_INVALID'))) from None


def registration(read_batch_metainfo,*,source_factory=BatchFilesSource,
                 verifier=verify_selected_batch_episode,staging_kind=None):
    if staging_kind is not None and (type(staging_kind) is not str or not staging_kind.strip() or len(staging_kind)>64):
        raise ValueError('invalid batch staging successor')
    if not inspect.iscoroutinefunction(read_batch_metainfo):
        raise ValueError('Trusted hash-only asynchronous metadata reader required')

    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'unlock_job_id'} or context.claim.event_id is None:
                raise ValueError()
            unlock=integer(payload['unlock_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        source=source_factory(context.configuration.value('storage.database_path'))
        try:
            digest=await blocking(source.source_hash,context.claim,unlock)
            raw=await read_batch_metainfo(digest,context.configuration,context.cancelled)
            inventory=await blocking(parse_batch_metainfo,raw,digest)
            intent,fingerprint,planned=await blocking(
                source.load,context.claim,unlock,inventory)
            protected=(context.configuration.value('storage.trial_root'),
                       context.configuration.value('storage.keep_root'),
                       context.configuration.value('storage.database_path'))
            facts=[]
            for index,episode in planned:
                if context.cancelled.is_set():
                    import asyncio
                    raise asyncio.CancelledError()
                media=await blocking(verifier,intent,index,unlock,fingerprint,
                                     context.cancelled,protected_roots=protected)
                facts.append((index,episode,media))
            return Outcome(value={'unlock_job_id':unlock,'files':tuple(facts),
                                  'verification_job_id':context.claim.job_id})
        except MetadataSourceWaiting as exc:
            return Outcome('defer',exc.reason_code,delay_ms=exc.delay_ms)
        except MetadataSourceUnavailable as exc:
            return Outcome('retry',exc.reason_code)
        except (MetadataSourceConfigurationError,MetadataSourceDenied) as exc:
            return Outcome('review',exc.reason_code)
        except (MediaUnavailable,ProbeUnavailable):
            return Outcome('retry','MEDIA_VERIFICATION_UNAVAILABLE')
        except (MediaInvalid,AcquisitionConflict,MetadataInvalid) as exc:
            return Outcome('review',exc.reason_code)
    def route(value):
        return () if staging_kind is None else (
            Successor.create(staging_kind,{'media_job_id':value['verification_job_id']}),)
    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=() if staging_kind is None else (staging_kind,))
