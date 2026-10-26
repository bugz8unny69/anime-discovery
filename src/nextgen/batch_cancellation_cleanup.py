"""Conservative cancelled-batch owner reconstruction and one-shot cleanup.

A canceled operation is not an acquisition permit. Frozen submission inventory
and provider episode facts are revalidated only to identify what can be safely
stopped and removed. No unstored path ever grants file deletion authority.
"""
import json
from types import SimpleNamespace
from src.nextgen.acquisition.metadata import (
    BatchInventory,TorrentFile,AcquisitionConflict,
)
from src.nextgen.acquisition.owned_cleanup import OwnedCleanup
from src.nextgen.acquisition.cleanup import FileCleanup
from src.nextgen.cancellation import CancellationError
from src.nextgen.storage.batch_acquisition_candidate import BatchAcquisitionCandidate
from src.nextgen.storage.batch_submission_journal import _intent
from src.nextgen.history import job_attempt,append_job_history


def load_cancelled_batch(db,operation_id,plan_id):
    """Only use inside exclusive cancellation gate and worker DB transaction."""
    source=db.execute(
        "SELECT s.reservation_job_id,s.info_hash,s.info_sha256,s.state,"
        "i.inventory_json,s.plan_id "
        "FROM batch_torrent_submissions s "
        "JOIN batch_submission_inventories i USING(plan_id) "
        "JOIN batch_episode_reservations r ON r.plan_id=s.plan_id "
        "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
        "JOIN job_operations o ON o.operation_id=m.operation_id "
        "WHERE s.plan_id=? AND m.operation_id=? "
        "AND o.state IN ('CANCEL_REQUESTED','CANCELED') "
        "AND r.state='ACTIVE' LIMIT 1",
        (plan_id,operation_id)).fetchone()
    if source is None or source[3]!='OWNED_STOPPED':
        raise CancellationError()
    reservation,digest,sha,_,raw,plan=source
    try:
        def unique(pairs):
            value={}
            for k,v in pairs:
                if k in value:raise CancellationError()
                value[k]=v
            return value
        data=json.loads(raw,object_pairs_hook=unique)
        if type(data) is not dict or set(data)!={'files'} or type(data['files']) is not list:
            raise CancellationError()
        files=tuple(TorrentFile(**f) for f in data['files'])
        inventory=BatchInventory(digest,sha,files)
        if inventory.json()!=raw:raise CancellationError()
    except (KeyError,TypeError,ValueError):
        raise CancellationError() from None
    rows=db.execute(
        "SELECT r.file_index,r.tvdb_episode,f.file_path,f.file_size_bytes "
        "FROM batch_episode_reservations r "
        "JOIN batch_trial_plans p USING(plan_id) "
        "JOIN batch_verified_files f ON f.batch_id=p.batch_id AND f.file_index=r.file_index "
        "JOIN batch_trial_files t ON t.plan_id=r.plan_id AND t.file_index=r.file_index "
        "AND t.tvdb_episode=r.tvdb_episode AND t.selected_size_bytes=f.file_size_bytes "
        "WHERE r.plan_id=? AND r.owner_job_id=? AND r.state='ACTIVE' "
        "ORDER BY r.tvdb_episode,r.file_index",
        (plan,reservation)).fetchall()
    count=db.execute('SELECT count(*) FROM batch_trial_files WHERE plan_id=?',
                     (plan,)).fetchone()[0]
    if len(rows)!=count or not 1<=len(rows)<=32:
        raise CancellationError()
    selected=set();episodes=[];total=0;probe=None
    for index,episode,path,size in rows:
        if (index in selected or index<0 or index>=len(files)
                or files[index].path!=path or files[index].size!=size or size<=0):
            raise CancellationError()
        selected.add(index);episodes.append((episode,index));total+=size
        if episode==1:
            if probe is not None:raise CancellationError()
            probe=index
    stored=db.execute(
        'SELECT planned_size_bytes FROM batch_trial_plans WHERE plan_id=?',
        (plan,)).fetchone()
    if probe is None or stored!=(total,):
        raise CancellationError()
    # Any other active scope using the same infohash is not ours to delete.
    foreign=db.execute(
        "SELECT 1 FROM batch_episode_reservations r "
        "JOIN batch_trial_plans p USING(plan_id) "
        "JOIN batch_verifications b USING(batch_id) "
        "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
        "WHERE b.info_hash=? AND m.operation_id<>? "
        "AND r.state='ACTIVE' LIMIT 1",(digest,operation_id)).fetchone()
    if foreign:raise CancellationError()
    candidate=BatchAcquisitionCandidate(
        reservation,plan,digest,sha,probe,tuple(episodes),
        tuple(f.index for f in files if f.index not in selected),total)
    intent=_intent(db,candidate,inventory)
    if intent is None or intent.state!='OWNED_STOPPED':raise CancellationError()
    from src.nextgen.batch_decision_cleanup import batch_cleanup_intent
    return batch_cleanup_intent(intent)


class BatchCanceledCleanup(OwnedCleanup):
    cleanup_event='CANCELLATION_CONTROL_RECORDED'
    complete_reason='CANCELLATION_COMPLETE'
    pending_reason='CANCELLATION_PENDING'

    def __init__(self,service):
        self.configuration=service.configuration
        self.secrets=service.secrets
        self.queue=service.queue
        self.client_factory=service.client_factory
        self.files_factory=service.files_factory
        self.component=service.component
        self._external_fence=service._fence
        self._log=service._log
        self.guard=service.guard

    def _fence(self,db=None):
        self._external_fence(db)

    def _journal(self,op,intent):
        from src.nextgen.storage.sqlite import transaction
        with self.queue.connection() as db,transaction(db):
            self._fence(db)
            load_cancelled_batch(db,op,intent.plan.plan_id)
            row=db.execute(
                'SELECT operation_id,fingerprint,files_json,phase '
                'FROM batch_cancellation_cleanup WHERE plan_id=?',
                (intent.plan.plan_id,)).fetchone()
            if row is not None:
                if row[:2]!=(op,intent.fingerprint):raise CancellationError()
                return json.loads(row[2]),row[3]
            now=self.queue.now()
            db.execute(
                "INSERT INTO batch_cancellation_cleanup("
                "plan_id,operation_id,fingerprint,files_json,phase,created_at_ms,updated_at_ms)"
                " VALUES(?,?,?,?,'PREPARED',?,?)",
                (intent.plan.plan_id,op,intent.fingerprint,'{}',now,now))
            return {},'PREPARED'

    def _advance(self,intent,prior,phase,files=None):
        from src.nextgen.storage.sqlite import transaction
        with self.queue.connection() as db,transaction(db):
            self._fence(db)
            row=db.execute(
                'SELECT operation_id FROM batch_cancellation_cleanup WHERE plan_id=?',
                (intent.plan.plan_id,)).fetchone()
            if row is None:raise CancellationError()
            load_cancelled_batch(db,row[0],intent.plan.plan_id)
            now=self.queue.now()
            if files is None:
                updated=db.execute(
                    'UPDATE batch_cancellation_cleanup SET phase=?,updated_at_ms=? '
                    'WHERE plan_id=? AND phase=?',
                    (phase,now,intent.plan.plan_id,prior)).rowcount
            else:
                raw=json.dumps(files,sort_keys=True,separators=(',',':'),allow_nan=False)
                if len(raw.encode())>1048576:raise CancellationError()
                updated=db.execute(
                    'UPDATE batch_cancellation_cleanup SET phase=?,files_json=?,updated_at_ms=? '
                    'WHERE plan_id=? AND phase=?',
                    (phase,raw,now,intent.plan.plan_id,prior)).rowcount
            if updated!=1:raise CancellationError()
            receipt=append_job_history(
                db,job_id=intent.plan.preparation_job_id,
                event_code=self.cleanup_event,
                reason_code=self.complete_reason if phase=='COMPLETE' else self.pending_reason,
                component=self.component,occurred_at_ms=now,
                details={'attempt':job_attempt(db,intent.plan.preparation_job_id)})
        self._log((receipt,))
