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
    load_batch, persist_observations, FallbackCompletion, load_fallback,
    persist_fallback, FallbackMissing, persist_fallback_missing,
)
from src.nextgen.worker import blocking
from src.nextgen import sonarr

REGISTERED_DELAY_MS = 120000  # Let Sonarr finish its post-add series refresh.
LISTING_ATTEMPTS = 10  # ~20 minutes of waiting for Sonarr to list the season.


def register_series(configuration, secrets, tvdb_series_id, *, client_factory=sonarr.Client):
    """Add a missing series to Sonarr unmonitored, with no searches, via the Keep client."""
    from types import SimpleNamespace
    options = sonarr.Options.capture(configuration, SimpleNamespace(
        staging_root=configuration.value('storage.keep_root')))
    client = client_factory(options, secrets.sonarr_api_key())
    if client.series(tvdb_series_id) is not None: return
    selection = SimpleNamespace(tvdb_series_id=tvdb_series_id)
    try: client.request('series', body=client.add_payload(selection, monitored=False))
    except sonarr.KeepReview:
        # Another job may have added it first; anything else needs review.
        if client.series(tvdb_series_id) is None: raise

KIND = 'DISCOVER_SONARR_BACKFILL'
DEFINITION = HandlerDefinition(KIND, 'Discover missing backfill episodes in Sonarr')


def registration(secrets, *, client_factory=Client.from_context, select_candidates=False,
                 acquire_candidates=False, register=register_series):
    if (type(select_candidates) is not bool or type(acquire_candidates) is not bool
            or acquire_candidates and not select_candidates):
        raise ValueError('Sonarr acquisition requires opted-in source selection')
    async def execute(context):
        payload = context.data()
        try:
            if (set(payload) not in ({'plan_id','start'},
                                    {'plan_id','start','fallback_episode'},
                                    {'plan_id','start','exhausted_episode'})
                    or context.claim.event_id is None):
                raise ValueError()
            plan_id = integer(payload['plan_id'], positive=True)
            start = integer(payload['start'], positive=True)
            if (start-1) % PAGE_SIZE: raise ValueError()
            fallback_episode = (integer(payload['fallback_episode'],positive=True)
                                if 'fallback_episode' in payload else None)
            exhausted_episode = (integer(payload['exhausted_episode'],positive=True)
                                 if 'exhausted_episode' in payload else None)
        except (ValueError, TypeError):
            return Outcome('review', 'JOB_PAYLOAD_INVALID')
        try:
            plan = await blocking(load_batch,
                context.configuration.value('storage.database_path'),plan_id,start)
            if exhausted_episode is not None:
                if not acquire_candidates or exhausted_episode not in plan.numbers:
                    raise BackfillConflict()
                return Outcome('review','SONARR_CANDIDATES_EXHAUSTED')
            client = client_factory(context.configuration,secrets)
            if fallback_episode is not None:
                if not acquire_candidates or fallback_episode not in plan.numbers:
                    raise BackfillConflict()
                target=await blocking(load_fallback,
                    context.configuration.value('storage.database_path'),
                    plan_id,fallback_episode)
                result=await blocking(client.search,target.identity)
                from src.nextgen.acquisition.sonarr_search import CandidateSelection, _magnet_hash
                release=next((row for row in result.candidates
                    if row.info_hash==target.next_hash
                    and client.policy.accepts(row)
                    and row.mapped_episode_ids==(result.episode_id,)
                    and _magnet_hash(row.magnet_url)==target.next_hash),None)
                if release is None:
                    return Outcome(value=FallbackMissing(plan,fallback_episode,target))
                return Outcome(value=FallbackCompletion(
                    plan,fallback_episode,target,
                    CandidateSelection(target.identity,result,release,client.policy)))
            observed = await blocking(
                client.backfill,plan.tvdb_series_id,plan.season,plan.numbers,
                reserved=plan.reserved,verified_ids=dict(plan.verified),
                **({'select_candidates': True} if select_candidates else {}))
            if len(observed) != len(plan.numbers):
                raise BackfillConflict()
            # Sonarr lists none of this page yet (e.g. still refreshing a newly
            # added series): wait and search again rather than record NOT_LISTED.
            if (any(o.status == 'NOT_LISTED' for o in observed)
                    and all(o.status in ('NOT_LISTED','IN_PROGRESS') for o in observed)
                    and context.claim.attempt < LISTING_ATTEMPTS):
                return Outcome('defer','SONARR_EPISODES_NOT_LISTED',delay_ms=REGISTERED_DELAY_MS)
            return Outcome(value=BackfillCompletion(plan,observed))
        except BackfillConflict:
            return Outcome('review','SONARR_BACKFILL_PLAN_CONFLICT')
        except SearchNotFound:
            try:
                await blocking(register, context.configuration, secrets, plan.tvdb_series_id)
            except sonarr.KeepConfiguration:
                return Outcome('review','SONARR_DISCOVERY_CONFIGURATION_INVALID')
            except sonarr.KeepReview:
                return Outcome('review','SONARR_DISCOVERY_REVIEW')
            except sonarr.KeepUnavailable:
                return Outcome('retry','SONARR_DISCOVERY_UNAVAILABLE')
            return Outcome('defer','SONARR_DISCOVERY_EPISODE_NOT_FOUND', delay_ms=REGISTERED_DELAY_MS)
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
        try:
            if type(value) is FallbackCompletion:
                return persist_fallback(db,claim,value)
            if type(value) is FallbackMissing:
                return persist_fallback_missing(db,claim,value)
            return persist_observations(db,claim,value,dispatch=acquire_candidates)
        except BackfillConflict:
            raise CompletionRejected(Outcome('review','SONARR_BACKFILL_PLAN_CONFLICT')) from None

    def route(value):
        if type(value) in (FallbackCompletion,FallbackMissing): return ()
        if type(value) is not BackfillCompletion: raise ValueError('typed backfill result required')
        next_start=value.plan.start+len(value.plan.numbers)
        if next_start>value.plan.backfill_count: return ()
        return (Successor.create(KIND,{'plan_id':value.plan.plan_id,'start':next_start}),)

    return Registration(KIND,DEFINITION,execute,persist=persist,route=route,
                        successor_kinds=(KIND,))
