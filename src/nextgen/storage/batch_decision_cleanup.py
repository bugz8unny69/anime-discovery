"""Durable explicit-decision cleanup for exactly owned batch torrent files.

A one-time stopped qB control is followed by a one-time remove
(deleteFiles=false). Local files are removed only afterward from the
captured inode/size inventory. Neither API command is rearmed on retries.
"""
from dataclasses import dataclass
import json

from src.nextgen.acquisition.cleanup import CleanupPermit
from src.nextgen.acquisition.metadata import BatchInventory
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.batch.owned_cleanup import (
    BatchOwnedCleanupIntent, owned_batch_observation,
    cleanup_fingerprint,
)
from src.nextgen.cancellation import CancellationError
from src.nextgen.history import append_job_history, integer, job_attempt
from src.nextgen.storage.batch_decisions import batch_staged
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import enqueue_job, transaction


KIND='CLEANUP_BATCH_DECIDED_DOWNLOAD'


def enqueue(db,claim,*,action):
    """In decision/Keep-cleanup completion transaction; no IO permission."""
    if not db.in_transaction or action not in ('KEEP','REJECT'):
        raise CancellationError()
    if action=='KEEP':
        if claim.kind!='CLEANUP_KEPT_BATCH_STAGE':
            raise CancellationError()
        source=db.execute(
            "SELECT keep_job_id,phase FROM batch_stage_cleanups "
            "WHERE job_id=?",(claim.job_id,)).fetchone()
        if source is None or source[1]!='COMPLETE':raise CancellationError()
        decision=source[0]
    else:
        if claim.kind!='REJECT_MEDIA':raise CancellationError()
        decision=claim.job_id
        if db.execute(
            "SELECT cleanup_state FROM anime_review_decisions "
            "WHERE job_id=? AND decision='REJECT'",
            (decision,)).fetchone()!=('COMPLETE',):
            raise CancellationError()
    management=db.execute(
        "SELECT operation_id,target_job_id,action FROM management_actions "
        "WHERE job_id=?",(decision,)).fetchone()
    if management is None or management[2]!=action:raise CancellationError()
    batch=batch_staged(db,management[0])
    if not batch:raise CancellationError()
    plan=batch[0][1]
    existing=db.execute(
        "SELECT job_id FROM jobs WHERE kind=? AND created_by_job_id=?",
        (KIND,claim.job_id)).fetchone()
    if existing is not None:raise CancellationError()
    return enqueue_job(
        db,kind=KIND,payload={'decision_job_id':decision},
        component='worker',event_id=claim.event_id,
        created_by_job_id=claim.job_id)


@dataclass(frozen=True)
class CleanupScope:
    decision_job_id: int
    target_operation_id: int
    plan_id: int
    info_hash: str
    info_sha256: str
    marker: str
    options: DownloadOptions


@dataclass(frozen=True)
class CleanupRecord:
    phase: str
    files: dict
    fingerprint: str


class BatchDecisionJournal:
    def __init__(self,database,*,clock=None):
        self.queue=JobQueue(database,clock=clock)

    def _facts(self,db,claim,decision_job_id):
        self.queue._owns(db,claim,self.queue.now())
        if claim.kind!=KIND:raise CancellationError()
        lineage=db.execute(
            "SELECT j.created_by_job_id,j.event_id,p.kind,p.state,o.state,"
            "p.created_by_job_id "
            "FROM jobs j JOIN jobs p ON p.job_id=j.created_by_job_id "
            "JOIN job_operation_members jm ON jm.job_id=j.job_id "
            "JOIN job_operation_members pm ON pm.job_id=p.job_id "
            "AND pm.operation_id=jm.operation_id "
            "JOIN job_operations o ON o.operation_id=jm.operation_id "
            "WHERE j.job_id=?",(claim.job_id,)).fetchone()
        if lineage is None or lineage[1]!=claim.event_id or lineage[3:5]!=('DONE','ACTIVE'):
            raise CancellationError()
        if lineage[2]=='REJECT_MEDIA':
            if lineage[0]!=decision_job_id:raise CancellationError()
            action='REJECT'
            if db.execute(
                "SELECT cleanup_state FROM anime_review_decisions WHERE job_id=? "
                "AND decision='REJECT'",(decision_job_id,)).fetchone()!=('COMPLETE',):
                raise CancellationError()
        elif lineage[2]=='CLEANUP_KEPT_BATCH_STAGE':
            if lineage[5]!=decision_job_id:raise CancellationError()
            action='KEEP'
            if db.execute(
                "SELECT phase,keep_job_id FROM batch_stage_cleanups WHERE job_id=?",
                (lineage[0],)).fetchone()!=('COMPLETE',decision_job_id):
                raise CancellationError()
        else:raise CancellationError()
        control=db.execute(
            "SELECT operation_id,target_job_id,action "
            "FROM management_actions WHERE job_id=?",(decision_job_id,)).fetchone()
        if control is None or control[2]!=action:raise CancellationError()
        if operation(db,control[1])[:2]!=(control[0],'STAGED'):
            raise CancellationError()
        publications=batch_staged(db,control[0])
        plan_id=publications[0][1]
        if any(r[1]!=plan_id for r in publications):raise CancellationError()
        row=db.execute(
            "SELECT info_hash,info_sha256,ownership_marker,"
            "base_url,save_path,category,timeout_seconds "
            "FROM batch_torrent_submissions "
            "WHERE plan_id=? AND state='OWNED_STOPPED'",(plan_id,)).fetchone()
        if row is None:raise CancellationError()
        options=DownloadOptions(*row[3:])
        return CleanupScope(decision_job_id,control[0],plan_id,
                            row[0],row[1],row[2],options)

    def source_hash(self,claim,decision_job_id):
        integer(decision_job_id,positive=True)
        with self.queue.connection() as db,transaction(db):
            return self._facts(db,claim,decision_job_id).info_hash

    def _current(self,db,claim,decision_job_id,inventory):
        scope=self._facts(db,claim,decision_job_id)
        if (type(inventory) is not BatchInventory
                or (inventory.info_hash,inventory.info_sha256)!=
                    (scope.info_hash,scope.info_sha256)):
            raise CancellationError()
        fingerprint=cleanup_fingerprint(
            scope.plan_id,inventory,scope.options,scope.marker)
        intent=BatchOwnedCleanupIntent(
            scope.plan_id,inventory,scope.options,scope.marker,fingerprint)
        prior=db.execute(
            "SELECT cleanup_job_id,decision_job_id,target_operation_id,"
            "fingerprint,phase,files_json FROM batch_download_cleanups "
            "WHERE plan_id=?",(scope.plan_id,)).fetchone()
        if prior is None:return intent,None
        if prior[:4]!=(claim.job_id,scope.decision_job_id,
                       scope.target_operation_id,fingerprint):
            raise CancellationError()
        try:files=json.loads(prior[5])
        except (ValueError,TypeError):raise CancellationError() from None
        return intent,CleanupRecord(prior[4],files,prior[3])

    def load(self,claim,decision_job_id,inventory):
        with self.queue.connection() as db,transaction(db):
            intent,prior=self._current(db,claim,decision_job_id,inventory)
            if prior is not None:return intent,prior
            row=self._facts(db,claim,decision_job_id)
            now=self.queue.now()
            db.execute(
                "INSERT INTO batch_download_cleanups "
                "(plan_id,cleanup_job_id,decision_job_id,target_operation_id,"
                "fingerprint,phase,files_json,created_at_ms,updated_at_ms) "
                "VALUES(?,?,?,?,?,'PREPARED','{}',?,?)",
                (row.plan_id,claim.job_id,row.decision_job_id,
                 row.target_operation_id,intent.fingerprint,now,now))
            self.queue._owns(db,claim,self.queue.now())
            return intent,CleanupRecord('PREPARED',{},intent.fingerprint)

    def advance(self,claim,decision_job_id,intent,prior,phase,*,files=None):
        if (prior,phase) not in (
                ('PREPARED','STOP_UNCERTAIN'),
                ('PREPARED','REMOVE_UNCERTAIN'),
                ('STOP_UNCERTAIN','REMOVE_UNCERTAIN'),
                ('REMOVE_UNCERTAIN','FILES'),
                ('FILES','COMPLETE')):
            raise CancellationError()
        with self.queue.connection() as db,transaction(db):
            current,record=self._current(db,claim,decision_job_id,intent.inventory)
            if current!=intent or record is None or record.phase!=prior:
                raise CancellationError()
            if files is None:files=record.files
            if type(files) is not dict:raise CancellationError()
            raw=json.dumps(files,sort_keys=True,separators=(',',':'),allow_nan=False)
            if len(raw.encode())>1048576:raise CancellationError()
            now=self.queue.now()
            db.execute(
                "UPDATE batch_download_cleanups SET phase=?,files_json=?,"
                "updated_at_ms=? WHERE plan_id=? AND phase=?",
                (phase,raw,now,intent.plan_id,prior))
            if phase=='COMPLETE':
                # Exactly this owned batch can release its per-file reservations.
                ids=db.execute(
                    "SELECT reservation_id FROM batch_episode_reservations "
                    "WHERE plan_id=? AND state='ACTIVE'",(intent.plan_id,)).fetchall()
                expected=db.execute(
                    "SELECT count(*) FROM batch_trial_files WHERE plan_id=?",
                    (intent.plan_id,)).fetchone()[0]
                if len(ids)!=expected:raise CancellationError()
                for (reservation,) in ids:
                    db.execute(
                        "UPDATE batch_episode_reservations SET state='RELEASED',"
                        "ended_at_ms=?,ended_by_job_id=? "
                        "WHERE reservation_id=? AND state='ACTIVE'",
                        (now,claim.job_id,reservation))
            audit=append_job_history(
                db,job_id=claim.job_id,
                event_code='DECISION_DOWNLOAD_CONTROL_RECORDED',
                reason_code=('DECISION_DOWNLOAD_CLEANUP_COMPLETE' if
                             phase=='COMPLETE' else 'DECISION_DOWNLOAD_CLEANUP_WAITING'),
                component='worker',occurred_at_ms=now,
                details={'attempt':job_attempt(db,claim.job_id)})
            self.queue._owns(db,claim,self.queue.now())
            return CleanupRecord(phase,files,intent.fingerprint),(audit,)

    def guard_send(self,claim,decision_job_id,intent,phase):
        with self.queue.connection() as db,transaction(db):
            current,record=self._current(db,claim,decision_job_id,intent.inventory)
            if current!=intent or record is None or record.phase!=phase:
                raise CancellationError()
            if phase not in ('STOP_UNCERTAIN','REMOVE_UNCERTAIN'):
                raise CancellationError()
            self.queue._owns(db,claim,self.queue.now())

    def guard(self,claim,decision_job_id,intent):
        with self.queue.connection() as db,transaction(db):
            current,record=self._current(db,claim,decision_job_id,intent.inventory)
            if current!=intent or record is None or record.phase not in ('FILES','COMPLETE'):
                raise CancellationError()
            self.queue._owns(db,claim,self.queue.now())
