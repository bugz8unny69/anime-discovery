"""Finish an explicit Reject decision and its selected staged-file cleanup."""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.review_decisions import staged, remove_selected
from src.nextgen.storage.sqlite import transaction
from src.nextgen.staging import StagingReview
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.cancellation import CancellationError

KIND='REJECT_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Reject anime and remove selected staged video')


def _persist(db,claim,value):
    row=db.execute("SELECT cleanup_state FROM anime_review_decisions WHERE job_id=? AND decision='REJECT'",(claim.job_id,)).fetchone()
    if row!=('COMPLETE',):raise CompletionRejected(Outcome('review','REJECT_CLEANUP_REVIEW'))
    from src.nextgen.decision_download_cleanup import enqueue
    enqueue(db,claim,claim.job_id)


def registration():
    async def execute(context):
        actions=ManagementActions(context.configuration.value('storage.database_path'))
        try:target=await blocking(actions.bind,context.claim,'REJECT')
        except (ActionUnavailable,ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        def guard():
            if context.cancelled.is_set():raise CancellationError()
            with actions.queue.connection() as db,transaction(db):actions.queue._owns(db,context.claim,actions.queue.now())
        def run():
            with actions.queue.connection() as db,transaction(db):
                actions.queue._owns(db,context.claim,actions.queue.now())
                row=db.execute('SELECT operation_id,anidb_id,cleanup_state FROM anime_review_decisions WHERE job_id=?',
                               (context.claim.job_id,)).fetchone()
                if row is None:raise StagingReview()
                source=staged(db,row[0])
                if source[0]!=row[1]:raise StagingReview()
                if row[2]=='COMPLETE':return
            remove_selected(source[2],source[3],guard,context.configuration.value('storage.keep_root'))
            with actions.queue.connection() as db,transaction(db):
                actions.queue._owns(db,context.claim,actions.queue.now())
                db.execute("UPDATE anime_review_decisions SET cleanup_state='COMPLETE' WHERE job_id=?",(context.claim.job_id,))
        try:
            await blocking(run)
            return Outcome()
        except (StagingReview,MediaInvalid,CancellationError):return Outcome('review','REJECT_CLEANUP_REVIEW')
        except OSError:return Outcome('retry','STAGING_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
