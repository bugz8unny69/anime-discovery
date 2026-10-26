"""Read-only source of completed owned batch file verification facts."""
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.acquisition.metadata import BatchInventory
from src.nextgen.storage.batch_acquisition_candidate import _candidate
from src.nextgen.storage.batch_submission_journal import _intent
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction
from src.nextgen.history import integer


class BatchFilesSource:
    def __init__(self,database,*,clock=None):
        self.queue=JobQueue(database,clock=clock)

    def _facts(self,db,claim,unlock_job_id):
        self.queue._owns(db,claim,self.queue.now())
        if claim.kind!='VERIFY_BATCH_FILES':raise MediaInvalid()
        row=db.execute(
            "SELECT j.event_id,j.kind,j.state,o.state,s.reservation_job_id,"
            "s.info_hash,s.info_sha256,s.plan_id,u.fingerprint "
            "FROM jobs verifying "
            "JOIN jobs j ON j.job_id=verifying.created_by_job_id "
            "JOIN job_operation_members vm ON vm.job_id=verifying.job_id "
            "JOIN job_operation_members um ON um.job_id=j.job_id "
            "AND um.operation_id=vm.operation_id "
            "JOIN job_operations o ON o.operation_id=vm.operation_id "
            "JOIN batch_torrent_unlocks u ON u.unlock_job_id=j.job_id "
            "JOIN batch_torrent_submissions s ON s.plan_id=u.plan_id "
            "WHERE verifying.job_id=? AND j.job_id=? AND u.phase='COMPLETE' "
            "AND s.state='OWNED_STOPPED'",
            (claim.job_id,unlock_job_id)).fetchone()
        if row is None or row[:4]!=(claim.event_id,'UNLOCK_BATCH','DONE','ACTIVE'):
            raise MediaInvalid()
        return row

    def source_hash(self,claim,unlock_job_id):
        integer(unlock_job_id,positive=True)
        with self.queue.connection() as db,transaction(db):
            row=self._facts(db,claim,unlock_job_id)
            self.queue._owns(db,claim,self.queue.now())
            return row[5]

    def load(self,claim,unlock_job_id,inventory):
        if type(inventory) is not BatchInventory:raise MediaInvalid()
        with self.queue.connection() as db,transaction(db):
            row=self._facts(db,claim,unlock_job_id)
            if (row[5],row[6])!=(inventory.info_hash,inventory.info_sha256):
                raise MediaInvalid()
            candidate=_candidate(db,row[4],inventory)
            if candidate.plan_id!=row[7]:raise MediaInvalid()
            intent=_intent(db,candidate,inventory)
            if intent is None or intent.state!='OWNED_STOPPED':raise MediaInvalid()
            # Actual unlock completion and file ownership are checked by
            # the worker completion transaction as well.
            planned=db.execute(
                "SELECT t.file_index,t.tvdb_episode FROM batch_trial_files t "
                "WHERE t.plan_id=? ORDER BY t.tvdb_episode",
                (candidate.plan_id,)).fetchall()
            if tuple(planned)!=tuple(candidate.planned_episodes):
                raise MediaInvalid()
            self.queue._owns(db,claim,self.queue.now())
            return intent,row[8],tuple(planned)
