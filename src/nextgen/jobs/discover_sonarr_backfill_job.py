"""Read-only, opt-in frozen-window Sonarr backfill discovery worker."""
from src.nextgen.acquisition.sonarr_search import (
    Client, SearchConfiguration, SearchUnauthorized, SearchUnsupported,
    SearchNotFound, SearchReview, SearchUnavailable,
)
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import (
    CompletionRejected, Outcome, Registration, Successor,
)
from src.nextgen.storage.sonarr_backfill import (
    PAGE_SIZE, BackfillConflict, BackfillCompletion,
    load_batch, persist_observations,
)
from src.nextgen.worker import blocking

KIND = 'DISCOVER_SONARR_BACKFILL'
DEFINITION = HandlerDefinition(KIND, 'Discover missing backfill episodes in Sonarr')


def registration(secrets, *, client_factory=Client.from_context, select_candidates=False,
                 acquire_candidates=False):
    if (type(select_candidates) is not bool or type(acquire_candidates) is not bool
            or acquire_candidates and not select_candidates):
        raise ValueError('Sonarr acquisition requires opted-in source selection')
    async def execute(context):
        payload = context.data()
        try:
            if set(payload) != {'plan_id','start'} or context.claim.event_id is None:
                raise ValueError()
            plan_id = integer(payload['plan_id'], positive=True)
            start = integer(payload['start'], positive=True)
            if (start-1) % PAGE_SIZE: raise ValueError()
        except (ValueError, TypeError):
            return Outcome('review', 'JOB_PAYLOAD_INVALID')
        try:
            plan = await blocking(load_batch,
                context.configuration.value('storage.database_path'),plan_id,start)
            client = client_factory(context.configuration,secrets)
            observed = await blocking(
                client.backfill,plan.tvdb_series_id,plan.season,plan.numbers,
                reserved=plan.reserved,verified_ids=dict(plan.verified),
                **({'select_candidates': True} if select_candidates else {}))
            if len(observed) != len(plan.numbers):
                raise BackfillConflict()
            return Outcome(value=BackfillCompletion(plan,observed))
        except BackfillConflict:
            return Outcome('review','SONARR_BACKFILL_PLAN_CONFLICT')
        except SearchNotFound:
            return Outcome('hold','SONARR_DISCOVERY_EPISODE_NOT_FOUND')
        except SearchUnauthorized:
            return Outcome('review','SONARR_DISCOVERY_AUTH_FAILED')
        except SearchUnsupported:
            return Outcome('review','SONARR_DISCOVERY_UNSUPPORTED')
        except SearchConfiguration:
            return Outcome('review','SONARR_DISCOVERY_CONFIGURATION_INVALID')
        except SearchReview:
            return Outcome('review','SONARR_DISCOVERY_REVIEW')
        except SearchUnavailable:
            return Outcome('retry','SONARR_DISCOVERY_UNAVAILABLE')

    def persist(db,claim,value):
        try: return persist_observations(db,claim,value,dispatch=acquire_candidates)
        except BackfillConflict:
            raise CompletionRejected(Outcome('review','SONARR_BACKFILL_PLAN_CONFLICT')) from None

    def route(value):
        if type(value) is not BackfillCompletion: raise ValueError('typed backfill result required')
        next_start=value.plan.start+len(value.plan.numbers)
        if next_start>value.plan.backfill_count: return ()
        return (Successor.create(KIND,{'plan_id':value.plan.plan_id,'start':next_start}),)

    return Registration(KIND,DEFINITION,execute,persist=persist,route=route,
                        successor_kinds=(KIND,))
