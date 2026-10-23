"""Verify a declared episode through providers; this job never acquires content."""
import inspect

from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.providers.errors import (ProviderDeferred, ProviderUnavailable, ProviderInvalidResponse,
                                          ProviderAuthenticationFailed)
from src.nextgen.release_contracts import VerifiedRelease, ReleaseNotReady, ReleaseConflict
from src.nextgen.storage.releases import load_release, persist_release
from src.nextgen.worker import blocking

KIND="VERIFY_RELEASE"
DEFINITION=HandlerDefinition(KIND,"Verify release episode")


def _persist(db,claim,value):
    try: persist_release(db,claim,value)
    except (ReleaseNotReady,ReleaseConflict) as exc:
        raise CompletionRejected(Outcome("review",exc.reason_code)) from None


def registration(verify):
    if not inspect.iscoroutinefunction(verify): raise ValueError("async release verifier required")

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
        return Outcome(value=result)

    # Terminal verification step until trial policy/resource claims are designed.
    # No acquisition routing, even for a proven declared episode.
    return Registration(KIND,DEFINITION,execute,persist=_persist)
