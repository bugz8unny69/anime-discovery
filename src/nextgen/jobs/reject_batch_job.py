"""Reject all published episodes in a verified batch without broad deletes."""
from src.nextgen.async_io import blocking
from src.nextgen.cancellation import CancellationError
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.batch_keep_imports import batch_publications
from src.nextgen.storage.review_decisions import remove_selected
from src.nextgen.storage.sqlite import transaction
from src.nextgen.storage.cancellation import operation
from src.nextgen.staging import StagingReview
from src.nextgen.acquisition.media import MediaInvalid

KIND='REJECT_BATCH'
DEFINITION=HandlerDefinition(KIND,'Reject all staged batch episodes safely')


def _persist(db,claim,value):
    state=db.execute(
        "SELECT cleanup_state FROM anime_review_decisions "
        "WHERE job_id=? AND decision='REJECT'",(claim.job_id,)).fetchone()
    if state!=('COMPLETE',):
        raise CompletionRejected(Outcome('review','REJECT_CLEANUP_REVIEW'))
    # Batch source files/torrent are NOT a single-episode acquisition.
    # Do not enqueue the single-file download cleanup handler here.


def registration():
    async def execute(context):
        actions=ManagementActions(context.configuration.value('storage.database_path'))
        try:target=await blocking(actions.bind,context.claim,'REJECT')
        except (ActionUnavailable,ValueError,TypeError):
            return Outcome('review','JOB_PAYLOAD_INVALID')

        def guard():
            if context.cancelled.is_set():raise CancellationError()
            with actions.queue.connection() as db,transaction(db):
                actions.queue._owns(db,context.claim,actions.queue.now())
                if operation(db,target)[1]!='STAGED':raise StagingReview()
                row=db.execute(
                    "SELECT operation_id,anidb_id,cleanup_state "
                    "FROM anime_review_decisions WHERE job_id=?",
                    (context.claim.job_id,)).fetchone()
                if row is None or row[0]!=operation(db,target)[0]:
                    raise StagingReview()
                staged=batch_publications(db,row[0])
                if any(item[4]!=row[1] for item in staged):
                    raise StagingReview()
                return staged,row[2]

        def run():
            rows,state=guard()
            if state=='COMPLETE':return
            for record in rows:
                _,_,manifest,receipts,*_=record
                remove_selected(
                    manifest,receipts,lambda:guard(),
                    context.configuration.value('storage.keep_root'))
            with actions.queue.connection() as db,transaction(db):
                actions.queue._owns(db,context.claim,actions.queue.now())
                staged,state=guard_readonly(db,context.claim,target)
                if state=='COMPLETE':return
                db.execute(
                    "UPDATE anime_review_decisions SET cleanup_state='COMPLETE' "
                    "WHERE job_id=? AND cleanup_state='PENDING'",
                    (context.claim.job_id,))
        def guard_readonly(db,claim,target):
            row=db.execute(
                "SELECT operation_id,anidb_id,cleanup_state "
                "FROM anime_review_decisions WHERE job_id=?",
                (claim.job_id,)).fetchone()
            if row is None or operation(db,target)[:2]!=(row[0],'STAGED'):
                raise StagingReview()
            staged=batch_publications(db,row[0])
            if any(item[4]!=row[1] for item in staged):
                raise StagingReview()
            return staged,row[2]
        try:
            await blocking(run)
            return Outcome()
        except (StagingReview,MediaInvalid,CancellationError):
            return Outcome('review','REJECT_CLEANUP_REVIEW')
        except OSError:
            return Outcome('retry','STAGING_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
