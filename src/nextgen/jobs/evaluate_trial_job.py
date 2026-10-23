"""Evaluate immutable trial windows; no downloads, media or permanent Keep."""
from dataclasses import dataclass

from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration, Successor
from src.nextgen.storage.trials import load_trial_source, persist_trial
from src.nextgen.trial_policy import Window, TrialProposal, TrialConflict
from src.nextgen.worker import blocking

KIND='EVALUATE_TRIAL'
DEFINITION=HandlerDefinition(KIND,'Evaluate trial episode selection')


@dataclass(frozen=True)
class EvaluationCompletion:
    proposal: TrialProposal
    evaluation_job_id: int


def _persist(db,claim,value):
    if type(value) is not EvaluationCompletion or value.evaluation_job_id!=claim.job_id:
        raise ValueError('episode selection completion does not match its job')
    try:return (persist_trial(db,claim,value.proposal),)
    except TrialConflict as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration(*, reservation_kind=None):
    if reservation_kind is not None and (type(reservation_kind) is not str or not reservation_kind.strip()
                                         or len(reservation_kind)>64 or reservation_kind==KIND):
        raise ValueError('invalid episode reservation successor')
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'verification_job_id'} or context.claim.event_id is None:raise ValueError()
            job=integer(payload['verification_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            source=await blocking(load_trial_source,context.configuration.value('storage.database_path'),job,context.claim.event_id)
            value=TrialProposal(source,Window(context.configuration.value('trial.backfill_count'),
                                             context.configuration.value('trial.following_count')),
                                context.configuration.desired_revision)
        except TrialConflict:return Outcome('review','TRIAL_PLAN_CONFLICT')
        return Outcome(value=EvaluationCompletion(value,context.claim.job_id))

    def route(value):
        if type(value) is not EvaluationCompletion:raise ValueError('typed episode selection completion required')
        return () if reservation_kind is None else (Successor.create(reservation_kind,{'evaluation_job_id':value.evaluation_job_id}),)

    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=() if reservation_kind is None else (reservation_kind,))
