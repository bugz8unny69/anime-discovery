"""Shared Reject lifecycle for single episodes and verified season packs.

One action/lease/decision check and one idempotent selected-file deletion
loop. Only the durable staging-publication lookup varies with media scope.
No torrent-wide or recursive deletion is permitted.
"""
from src.nextgen.async_io import blocking
from src.nextgen.cancellation import CancellationError
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.staging import StagingBusy, StagingReview
from src.nextgen.storage.batch_keep_imports import batch_publications
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.review_decisions import staged, remove_selected
from src.nextgen.storage.sqlite import transaction
from src.nextgen.storage.staging import Journal as StageJournal


def _sources(db, actions, claim, target, *, batch):
    """Trusted proof tuples and decision state for this leased Reject action."""
    actions.queue._owns(db, claim, actions.queue.now())
    op=operation(db,target)
    action=db.execute(
        "SELECT target_job_id,operation_id FROM management_actions "
        "WHERE job_id=? AND action='REJECT'",(claim.job_id,)).fetchone()
    decision=db.execute(
        "SELECT operation_id,anidb_id,cleanup_state FROM anime_review_decisions "
        "WHERE job_id=? AND decision='REJECT'",(claim.job_id,)).fetchone()
    if (op[1]!='STAGED' or action!=(target,op[0])
            or decision is None or decision[0]!=op[0]
            or decision[2] not in ('PENDING','COMPLETE')):
        raise StagingReview()
    if batch:
        rows=batch_publications(db,op[0])
        if any(row[4]!=decision[1] for row in rows):
            raise StagingReview()
        sources=tuple((row[2],row[3]) for row in rows)
    else:
        row=staged(db,op[0])
        if row[0]!=decision[1]:
            raise StagingReview()
        sources=((row[2],row[3]),)
    if not sources:
        raise StagingReview()
    return sources,decision[2]


def _run(actions, context, target, *, batch, remove):
    # Serialize old draining and recovered attempts for this exact control job.
    with StageJournal(actions.queue.database).lock(context.claim):
        with actions.queue.connection() as db,transaction(db):
            sources,state=_sources(db,actions,context.claim,target,batch=batch)
        if state=='COMPLETE':
            return

        def guard():
            if context.cancelled.is_set():
                raise CancellationError()
            with actions.queue.connection() as db,transaction(db):
                current,phase=_sources(db,actions,context.claim,target,batch=batch)
                if phase!='PENDING' or current!=sources:
                    raise StagingReview()

        guard()
        for manifest,receipts in sources:
            remove(manifest,receipts,guard,
                   context.configuration.value('storage.keep_root'))
        with actions.queue.connection() as db,transaction(db):
            current,phase=_sources(db,actions,context.claim,target,batch=batch)
            if current!=sources:
                raise StagingReview()
            if phase=='COMPLETE':
                return
            if db.execute(
                "UPDATE anime_review_decisions SET cleanup_state='COMPLETE' "
                "WHERE job_id=? AND decision='REJECT' AND cleanup_state='PENDING'",
                (context.claim.job_id,)).rowcount!=1:
                raise StagingReview()


async def execute_reject(context, *, batch, remove=remove_selected):
    actions=ManagementActions(context.configuration.value('storage.database_path'))
    try:
        target=await blocking(actions.bind,context.claim,'REJECT')
    except (ActionUnavailable,ValueError,TypeError):
        return Outcome('review','JOB_PAYLOAD_INVALID')
    try:
        await blocking(_run,actions,context,target,batch=batch,remove=remove)
        return Outcome()
    except StagingBusy:
        return Outcome('defer','JOB_WAITING',delay_ms=1000)
    except (StagingReview,MediaInvalid,CancellationError,ValueError,TypeError,KeyError):
        return Outcome('review','REJECT_CLEANUP_REVIEW')
    except OSError:
        return Outcome('retry','STAGING_UNAVAILABLE')


def _persist(db,claim,value,*,batch):
    row=db.execute(
        "SELECT cleanup_state FROM anime_review_decisions "
        "WHERE job_id=? AND decision='REJECT'",(claim.job_id,)).fetchone()
    if row!=('COMPLETE',):
        raise CompletionRejected(Outcome('review','REJECT_CLEANUP_REVIEW'))
    if batch:
        from src.nextgen.jobs.cleanup_batch_download_job import enqueue
        enqueue(db,claim)
    else:
        from src.nextgen.decision_download_cleanup import enqueue
        enqueue(db,claim,claim.job_id)


def registration(kind,definition,*,batch):
    async def execute(context):
        return await execute_reject(context,batch=batch)
    def persist(db,claim,value):
        return _persist(db,claim,value,batch=batch)
    return Registration(kind,definition,execute,persist=persist)
