"""Reserve one selected, verified episode. External acquisition follows later."""
from src.nextgen.episode_reservations import ReservationConflict, EpisodeReserved
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration, Successor
from src.nextgen.storage.episode_reservations import load_reservation_input, persist_reservation
from src.nextgen.worker import blocking

KIND='RESERVE_EPISODE'
DEFINITION=HandlerDefinition(KIND,'Reserve episode for acquisition')


def _persist(db,claim,value):
    try:return (persist_reservation(db,claim,value),)
    except EpisodeReserved as exc:raise CompletionRejected(Outcome('hold',exc.reason_code)) from None
    except ReservationConflict as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration(*, preparation_kind=None):
    if preparation_kind is not None and (type(preparation_kind) is not str or not preparation_kind.strip()
                                        or len(preparation_kind)>64 or preparation_kind==KIND):
        raise ValueError('invalid acquisition preparation successor')
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'evaluation_job_id'} or context.claim.event_id is None:raise ValueError()
            job=integer(payload['evaluation_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            value=await blocking(load_reservation_input,context.configuration.value('storage.database_path'),job,context.claim.event_id)
        except ReservationConflict:return Outcome('review','EPISODE_RESERVATION_CONFLICT')
        return Outcome(value=value)
    def route(value):
        return () if preparation_kind is None or not value.selected else (
            Successor.create(preparation_kind,{'evaluation_job_id':value.evaluation_job_id}),)
    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=() if preparation_kind is None else (preparation_kind,))
