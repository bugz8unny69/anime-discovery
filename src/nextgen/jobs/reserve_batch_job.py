"""Opt-in RESERVE_BATCH gate; never submits, selects or starts a torrent.

Do not register this in the default worker until the crash-safe batch
acquisition journal and cancellation reconciler are installed.
"""
from src.nextgen.episode_reservations import ReservationConflict, EpisodeReserved
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.batch_reservations import (
    load_batch_reservation, persist_batch_reservations,
)
from src.nextgen.worker import blocking

KIND='RESERVE_BATCH'
DEFINITION=HandlerDefinition(KIND,'Reserve verified batch episodes')


def _persist(db,claim,value):
    from src.nextgen.storage.review_decisions import require_allowed, AnimeRejected
    try:
        require_allowed(db,value.anidb_id)
        return (persist_batch_reservations(db,claim,value),)
    except AnimeRejected as exc:
        raise CompletionRejected(Outcome('hold',exc.reason_code)) from None
    except EpisodeReserved as exc:
        raise CompletionRejected(Outcome('hold',exc.reason_code)) from None
    except ReservationConflict as exc:
        raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration():
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'evaluation_job_id'} or context.claim.event_id is None:
                raise ValueError()
            job=integer(payload['evaluation_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            result=await blocking(
                load_batch_reservation,
                context.configuration.value('storage.database_path'),
                job,context.claim.event_id)
        except ReservationConflict:
            return Outcome('review','EPISODE_RESERVATION_CONFLICT')
        return Outcome(value=result)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
