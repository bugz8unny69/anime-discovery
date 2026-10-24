"""Retryable Jellyfin scan handoff for completed Stage or verified Keep.

Refresh is never a prerequisite for staging, Sonarr import or successful Keep.
This job acknowledges only that the server accepted a library scan request.
"""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.jellyfin import (JellyfinOptions, JellyfinClient,
    JellyfinConfigurationInvalid, JellyfinUnavailable)
from src.nextgen.job_contracts import Outcome, Registration
from src.nextgen.secrets import SecretStorageError
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction

KIND="REFRESH_JELLYFIN"
DEFINITION=HandlerDefinition(KIND,"Request Jellyfin library scan")


def _source(queue,claim,kind,source_id):
    # Source facts are immutable, and only the worker's committed handoff
    # could have created this control job in its independent operation.
    with queue.connection() as db,transaction(db):
        queue._owns(db,claim,queue.now())
        row=db.execute("SELECT kind,state,event_id FROM jobs WHERE job_id=?",(source_id,)).fetchone()
        if (row is None or row!=(kind,"DONE",claim.event_id)
                or not db.execute("SELECT 1 FROM jobs WHERE job_id=? AND created_by_job_id=?",
                                  (claim.job_id,source_id)).fetchone()):
            return False
        if kind=="STAGE_TRIAL_MEDIA":
            return db.execute("SELECT 1 FROM staging_publications "
                "WHERE job_id=? AND state='PUBLISHED'",(source_id,)).fetchone() is not None
        return db.execute("SELECT 1 FROM keep_imports "
            "WHERE keep_job_id=? AND phase='VERIFIED' AND library_evidence_json IS NOT NULL",
            (source_id,)).fetchone() is not None


def registration(secrets,*,client_factory=JellyfinClient):
    async def execute(context):
        payload=context.data()
        if type(payload) is not dict or set(payload)!={"source_kind","source_job_id"}:
            return Outcome("review","JOB_PAYLOAD_INVALID")
        kind=payload["source_kind"]
        if kind not in ("STAGE_TRIAL_MEDIA","KEEP_MEDIA"):
            return Outcome("review","JOB_PAYLOAD_INVALID")
        try:source_id=integer(payload["source_job_id"],positive=True)
        except (ValueError,TypeError):return Outcome("review","JOB_PAYLOAD_INVALID")
        queue=JobQueue(context.configuration.value("storage.database_path"))
        if not await blocking(_source,queue,context.claim,kind,source_id):
            return Outcome("review","JELLYFIN_REFRESH_SOURCE_INVALID")
        if context.cancelled.is_set():
            return Outcome("retry","JELLYFIN_REFRESH_UNAVAILABLE")
        try:
            options=JellyfinOptions(context.configuration.value("jellyfin.base_url"),
                                   await blocking(secrets.jellyfin_api_key),
                                   context.configuration.value("jellyfin.timeout_seconds"))
            client=client_factory(options)
            await blocking(client.request_scan)
            return Outcome()
        except (JellyfinConfigurationInvalid,SecretStorageError):
            return Outcome("blocked","JELLYFIN_CONFIGURATION_INVALID")
        except JellyfinUnavailable:
            # A scan request can be safely repeated after a lost acknowledgment;
            # unlike a Sonarr import, it does not create new media files.
            return Outcome("retry","JELLYFIN_REFRESH_UNAVAILABLE")
    return Registration(KIND,DEFINITION,execute)
