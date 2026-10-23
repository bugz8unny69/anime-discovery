"""Evaluate immutable trial windows; no downloads, media or permanent Keep."""
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.trials import load_trial_source, persist_trial
from src.nextgen.trial_policy import Window, TrialProposal, TrialConflict
from src.nextgen.worker import blocking

KIND='EVALUATE_TRIAL'
DEFINITION=HandlerDefinition(KIND,'Evaluate trial episode selection')


def _persist(db,claim,value):
    try:return (persist_trial(db,claim,value),)
    except TrialConflict as exc:raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration():
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
        return Outcome(value=value)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
