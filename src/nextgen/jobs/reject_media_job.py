"""Finish an explicit Reject decision and its selected staged-file cleanup."""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.review_decisions import staged, remove_selected
from src.nextgen.storage.batch_decisions import batch_staged
from src.nextgen.storage.staging import Journal as StageJournal
from src.nextgen.storage.sqlite import transaction
from src.nextgen.staging import StagingReview, StagingBusy
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.cancellation import CancellationError

KIND='REJECT_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Reject anime and remove selected staged video')


def _persist(db,claim,value):
    row=db.execute("SELECT cleanup_state FROM anime_review_decisions WHERE job_id=? AND decision='REJECT'",(claim.job_id,)).fetchone()
    if row!=('COMPLETE',):raise CompletionRejected(Outcome('review','REJECT_CLEANUP_REVIEW'))
    target=db.execute(
        "SELECT operation_id FROM management_actions "
        "WHERE job_id=? AND action='REJECT'",(claim.job_id,)).fetchone()
    if target is None:raise CompletionRejected(Outcome('review','REJECT_CLEANUP_REVIEW'))
    batch=db.execute(
        "SELECT 1 FROM batch_staging_publications s "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "WHERE m.operation_id=? LIMIT 1",(target[0],)).fetchone()
    if batch is None:
        from src.nextgen.decision_download_cleanup import enqueue
        enqueue(db,claim,claim.job_id)
    else:
        # A batch has its own owned-torrent journal; never authorize the
        # single-file deletion helper against a multi-video source.
        pass


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
                try:
                    source=(staged(db,row[0]),)
                    batch=False
                except StagingReview:
                    source=batch_staged(db,row[0])
                    batch=True
                if any(entry[0]!=row[1] for entry in source):
                    raise StagingReview()
                if row[2]=='COMPLETE':return
            def remove_all():
                for entry in source:
                    manifest,receipts=(entry[4],entry[5]) if batch else (entry[2],entry[3])
                    remove_selected(manifest,receipts,guard,
                                    context.configuration.value('storage.keep_root'))
            if batch:
                with StageJournal(actions.queue.database).lock(context.claim):
                    remove_all()
            else:
                remove_all()
            with actions.queue.connection() as db,transaction(db):
                actions.queue._owns(db,context.claim,actions.queue.now())
                db.execute("UPDATE anime_review_decisions SET cleanup_state='COMPLETE' WHERE job_id=?",(context.claim.job_id,))
        try:
            await blocking(run)
            return Outcome()
        except StagingBusy:return Outcome('defer','STAGING_BUSY',delay_ms=1000)
        except (StagingReview,MediaInvalid,CancellationError):return Outcome('review','REJECT_CLEANUP_REVIEW')
        except OSError:return Outcome('retry','STAGING_UNAVAILABLE')
    return Registration(KIND,DEFINITION,execute,persist=_persist)
