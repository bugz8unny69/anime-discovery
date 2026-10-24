"""Scan the missing slots of a verified immutable trial window.

Search results are *only* inventoried. Release verification, torrent-manifest
retrieval, admission/reservation and downloads remain separate trusted stages.
"""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected,Outcome,Registration,Successor
from src.nextgen.missing_search import (ProwlarrClient,SearchOptions,
    SearchUnavailable,SearchConfigurationInvalid)
from src.nextgen.secrets import SecretStorageError
from src.nextgen.storage.missing_search import Batch,Results,SearchReview,load,persist
from src.nextgen.storage.review_decisions import AnimeRejected

KIND="DISCOVER_MISSING_EPISODES"
DEFINITION=HandlerDefinition(KIND,"Find other episodes in the configured trial window")


def _persist(db,claim,value):
    try:persist(db,claim,value)
    except (SearchReview,AnimeRejected) as exc:
        raise CompletionRejected(Outcome("review",exc.reason_code)) from None


def registration(secrets,*,client_factory=ProwlarrClient,loader=load):
    async def execute(context):
        payload=context.data()
        if type(payload) is not dict or set(payload)!={"evaluation_job_id"}:
            return Outcome("review","JOB_PAYLOAD_INVALID")
        try:
            evaluation=integer(payload["evaluation_job_id"],positive=True)
        except (ValueError,TypeError):
            return Outcome("review","JOB_PAYLOAD_INVALID")
        try:
            batch=await blocking(loader,context.configuration.value("storage.database_path"),
                                 evaluation,context.claim.event_id)
        except (SearchReview,AnimeRejected) as exc:
            return Outcome("hold",exc.reason_code) if isinstance(exc,AnimeRejected) else Outcome("review",exc.reason_code)
        if not batch.episodes:
            return Outcome(value=Results(batch,(),context.claim.job_id))
        try:
            opts=SearchOptions(context.configuration.value("prowlarr.base_url"),
                               await blocking(secrets.prowlarr_api_key),
                               context.configuration.value("prowlarr.timeout_seconds"))
            client=client_factory(opts)
        except (SearchConfigurationInvalid,SecretStorageError):
            return Outcome("blocked","MISSING_SEARCH_CONFIGURATION_INVALID")
        try:
            matches=[]
            for episode in batch.episodes:
                if context.cancelled.is_set():
                    return Outcome("retry","MISSING_SEARCH_UNAVAILABLE")
                candidates=await blocking(client.search,batch.title,batch.season,episode)
                matches.append((episode,candidates))
            return Outcome(value=Results(batch,tuple(matches),context.claim.job_id))
        except SearchUnavailable:
            return Outcome("retry","MISSING_SEARCH_UNAVAILABLE")
        except SearchConfigurationInvalid:
            return Outcome("blocked","MISSING_SEARCH_CONFIGURATION_INVALID")

    def route(value):
        if type(value) is not Results:raise ValueError("typed search inventory required")
        if not value.batch.has_more:return ()
        return (Successor.create(KIND,{"evaluation_job_id":value.batch.evaluation_job_id},
                                 independent=True),)

    return Registration(KIND,DEFINITION,execute,persist=_persist,route=route,
                        successor_kinds=(KIND,))
