"""EVALUATE_BATCH: durable trial intent, no torrent acquisition side effects."""
from dataclasses import dataclass

from src.nextgen.acquisition.settings import SizeLimitExceeded, SizeEvidenceMissing, size_limits
from src.nextgen.batch.durable_trial import BatchTrialProposal, propose_batch_trial
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.batch_trials import load_batch_trial_source, persist_batch_trial
from src.nextgen.trial_policy import Window, TrialConflict
from src.nextgen.worker import blocking

KIND='EVALUATE_BATCH'
DEFINITION=HandlerDefinition(KIND,'Plan verified batch episodes')


@dataclass(frozen=True)
class BatchEvaluationCompletion:
    proposal: BatchTrialProposal
    evaluation_job_id: int


def _persist(db,claim,value):
    if type(value) is not BatchEvaluationCompletion or value.evaluation_job_id!=claim.job_id:
        raise ValueError('Batch trial completion does not match its job')
    try:
        return (persist_batch_trial(db,claim,value.proposal),)
    except (TrialConflict,SizeLimitExceeded,SizeEvidenceMissing) as exc:
        raise CompletionRejected(Outcome('review',exc.reason_code)) from None


def registration():
    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={'verification_job_id'} or context.claim.event_id is None:
                raise ValueError()
            job=integer(payload['verification_job_id'],positive=True)
        except (ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')
        try:
            source=await blocking(load_batch_trial_source,
                context.configuration.value('storage.database_path'),job,context.claim.event_id)
            window=Window(context.configuration.value('trial.backfill_count'),
                          context.configuration.value('trial.following_count'))
            proposal=propose_batch_trial(source,window,size_limits(context.configuration),
                                          context.configuration.desired_revision)
        except (TrialConflict,SizeLimitExceeded,SizeEvidenceMissing) as exc:
            return Outcome('review',exc.reason_code)
        return Outcome(value=BatchEvaluationCompletion(proposal,context.claim.job_id))
    return Registration(KIND,DEFINITION,execute,persist=_persist)
