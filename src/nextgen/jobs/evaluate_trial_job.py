"""Evaluate immutable trial windows; no downloads, media or permanent Keep."""
from dataclasses import dataclass

from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration, Successor
from src.nextgen.storage.trials import load_trial_source, persist_trial
from src.nextgen.trial_policy import Window, TrialProposal, TrialConflict
from src.nextgen.worker import blocking

KIND='EVALUATE_TRIAL'
DEFINITION=HandlerDefinition(KIND,'Evaluate Intake episode selection')


@dataclass(frozen=True)
class EvaluationCompletion:
    proposal: TrialProposal
    evaluation_job_id: int
    discover_enabled: bool = False


def _persist(db,claim,value):
    if type(value) is not EvaluationCompletion or value.evaluation_job_id!=claim.job_id:
        raise ValueError('episode selection completion does not match its job')
    from src.nextgen.storage.review_decisions import require_allowed, AnimeRejected
    try:
        require_allowed(db,value.proposal.source.anidb_id)
        return (persist_trial(db,claim,value.proposal),)
    except AnimeRejected as exc:raise CompletionRejected(Outcome('hold',exc.reason_code)) from None
    except TrialConflict as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration(*, reservation_kind=None, discovery_kind=None):
    if discovery_kind is not None and (type(discovery_kind) is not str or not discovery_kind.strip()
            or len(discovery_kind)>64 or discovery_kind in (KIND,reservation_kind)):
        raise ValueError('invalid discovery successor')
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
        return Outcome(value=EvaluationCompletion(value,context.claim.job_id,
            bool(context.configuration.value('prowlarr.base_url'))))

    def route(value):
        if type(value) is not EvaluationCompletion:raise ValueError('typed episode selection completion required')
        successors=[]
        if reservation_kind is not None:
            successors.append(Successor.create(reservation_kind,{'evaluation_job_id':value.evaluation_job_id}))
        if discovery_kind is not None and value.discover_enabled:
            successors.append(Successor.create(discovery_kind,{'evaluation_job_id':value.evaluation_job_id},independent=True))
        return tuple(successors)

    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=tuple(x for x in (reservation_kind,discovery_kind) if x is not None))
