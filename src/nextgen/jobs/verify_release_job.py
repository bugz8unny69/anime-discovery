"""Verify a declared episode through providers; this job never acquires content."""
import inspect
from dataclasses import dataclass

from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration, Successor
from src.nextgen.providers.errors import (ProviderDeferred, ProviderUnavailable, ProviderInvalidResponse,
                                          ProviderAuthenticationFailed)
from src.nextgen.release_contracts import VerifiedRelease, ReleaseNotReady, ReleaseConflict
from src.nextgen.storage.releases import load_release, persist_release
from src.nextgen.worker import blocking

KIND="VERIFY_RELEASE"
DEFINITION=HandlerDefinition(KIND,"Verify release episode")


@dataclass(frozen=True)
class ReleaseCompletion:
    verified: VerifiedRelease
    verification_job_id: int


def _persist(db,claim,value):
    if type(value) is not ReleaseCompletion or value.verification_job_id!=claim.job_id:
        raise ValueError("release completion does not match its job")
    try: persist_release(db,claim,value.verified)
    except (ReleaseNotReady,ReleaseConflict) as exc:
        raise CompletionRejected(Outcome("review",exc.reason_code)) from None


def registration(verify, *, trial_kind=None):
    if not inspect.iscoroutinefunction(verify): raise ValueError("async release verifier required")
    if trial_kind is not None and (type(trial_kind) is not str or not trial_kind.strip()
                                   or len(trial_kind)>64 or trial_kind==KIND):
        raise ValueError("invalid trial evaluation successor")

    async def execute(context):
        payload=context.data()
        try:
            if set(payload)!={"anidb_id"} or context.claim.event_id is None:
                raise ValueError()
            aid=integer(payload["anidb_id"],positive=True)
        except (ValueError,TypeError): return Outcome("review","JOB_PAYLOAD_INVALID")
        try:
            source=await blocking(load_release,context.configuration.value("storage.database_path"),context.claim.event_id,aid)
            result=await verify(source,context.configuration,context.cancelled)
        except ProviderDeferred as exc: return Outcome("defer","JOB_WAITING",delay_ms=exc.delay_ms)
        except (ProviderUnavailable,ProviderInvalidResponse) as exc: return Outcome("retry",exc.reason_code)
        except ProviderAuthenticationFailed: return Outcome("review","PROVIDER_AUTH_FAILED")
        except (ReleaseNotReady,ReleaseConflict) as exc: return Outcome("review",exc.reason_code)
        if type(result) is not VerifiedRelease or result.source!=source:
            return Outcome("review","RELEASE_CONFLICT")
        return Outcome(value=ReleaseCompletion(result,context.claim.job_id))

    def route(value):
        if type(value) is not ReleaseCompletion:raise ValueError("typed release completion required")
        return () if trial_kind is None else (Successor.create(trial_kind,{'verification_job_id':value.verification_job_id}),)

    # Acquisition remains gated separately; only trial evaluation can follow.
    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=() if trial_kind is None else (trial_kind,))
