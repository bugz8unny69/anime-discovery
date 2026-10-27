"""API-ready cancellation library; invoke only after management authorization.

HTTP callers submit control jobs. Only a job in a distinct control operation
may invoke cleanup under existing maintenance admission, with a lease guard.
Cleanup always requires exclusive drain protection for the target operation.
"""
from contextlib import nullcontext
from src.nextgen.acquisition.cleanup import FileCleanup
from src.nextgen.acquisition.owned_cleanup import OwnedCleanup
from src.nextgen.acquisition.qbittorrent import Client
from src.nextgen.acquisition.submission import ClientUnavailable, ClientInvalid, ClientAuthenticationFailed, ClientUnsupported
from src.nextgen.cancellation import CancellationError, CleanupBusy, OperationGate
from src.nextgen.diagnostics import log_history
from src.nextgen.history import job_attempt, append_job_history
from src.nextgen.maintenance import MaintenanceGate
from src.nextgen.storage.cancellation import CancellationStore, operation, cancel_job
from src.nextgen.storage.sqlite import transaction
from src.nextgen.storage.submissions import _plan, _intent
from src.nextgen.staging_artifacts import BatchStageCleanupRetry


class CancellationService(OwnedCleanup):
    def __init__(self,configuration,secrets,*,client_factory=Client,files_factory=FileCleanup,logger=None,admitted=False,guard=None,component="api"):
        if type(admitted) is not bool or admitted and not callable(guard):raise CancellationError()
        from src.nextgen.history import component_name
        self.component=component_name(component)
        self.configuration,self.secrets=configuration,secrets
        self.database=configuration.value('storage.database_path')
        self.store=CancellationStore(self.database)
        self.queue=self.store.queue
        self.client_factory,self.files_factory,self.logger=client_factory,files_factory,logger
        self.gate=MaintenanceGate(self.database)
        self.admitted,self.guard=admitted,guard
    def _admission(self):
        return nullcontext() if self.admitted else self.gate.operation()
    def _fence(self,db=None):
        if self.guard is not None:self.guard(db)
    def _log(self,records):
        if self.logger is not None:
            for record in records:log_history(self.logger,record)
    def status(self,job_id):
        with self._admission():return self.store.status(job_id)
    def request(self,job_id):
        with self._admission():
            op,receipts=self.store.request(job_id)
            self._log(receipts)
            return op
    def cancel(self,job_id):
        self.request(job_id)
        return self.cleanup(job_id)
    def _state(self,job_id,state,reason,*,cause=None):
        with self.store.queue.connection() as db,transaction(db):
            self._fence(db)
            op=operation(db,job_id)
            if op[1] not in ('CANCEL_REQUESTED','CANCELED'):raise CancellationError()
            now=self.store.queue.now()
            db.execute("UPDATE job_operations SET state='CANCELED',cleanup_state=?,reason_code=?,updated_at_ms=? WHERE operation_id=?",
                       (state,reason,now,op[0]))
            records=() if (op[2],op[3])==(state,reason) else (append_job_history(db,job_id=job_id,
                event_code='CANCELLATION_CLEANUP_CHANGED',reason_code=reason,component=self.component,occurred_at_ms=now,
                details={**({} if cause is None else {'cause_reason_code':cause}),'attempt':job_attempt(db,job_id)}),)
            if state=='COMPLETE':
                from src.nextgen.storage.reservation_release import release_cancelled
                records+=release_cancelled(db,op[0],job_id,now,component=self.component)
        self._log(records)
    def _targets(self,job_id):
        with self.store.queue.connection() as db,transaction(db):
            self._fence(db)
            op=operation(db,job_id)
            if op[1] not in ('CANCEL_REQUESTED','CANCELED'):raise CancellationError()
            receipts=[];now=self.store.queue.now()
            # Exclusive OperationGate proves participating handlers have drained.
            for (member,) in db.execute('SELECT job_id FROM job_operation_members WHERE operation_id=?',(op[0],)).fetchall():
                receipts.extend(cancel_job(db,member,now,self.component))
            # v45 pre-manifest torrents are not yet covered by the manifest-
            # bounded deletion journal. Never release this operation's
            # reservation while one could remain in qBittorrent or on disk.
            pending=db.execute(
                "SELECT 1 FROM sonarr_magnet_intents i "
                "JOIN job_operation_members m ON m.job_id=i.job_id "
                "WHERE m.operation_id=? LIMIT 1",(op[0],)).fetchone()
            if pending:
                raise CancellationError()
            rows=db.execute('SELECT p.job_id,j.event_id FROM acquisition_plans p JOIN jobs j ON j.job_id=p.job_id '
                'JOIN job_operation_members m ON m.job_id=p.job_id WHERE m.operation_id=? ORDER BY p.plan_id',(op[0],)).fetchall()
            if len(rows)>1000:raise CancellationError()
            targets=[]
            for preparation,event in rows:
                plan=_plan(db,preparation,event)
                # Explicit other consumers, including older separately scoped jobs,
                # preserve resources. Provenance IDs are never traversed as edges.
                shared=db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) "
                    "WHERE m.operation_id<>? AND "
                    "((j.kind IN ('SUBMIT_TORRENT','DOWNLOAD_TORRENT') AND json_extract(j.payload_json,'$.preparation_job_id')=?) OR "
                    "(j.kind IN ('RESERVE_EPISODE','PREPARE_ACQUISITION') AND json_extract(j.payload_json,'$.evaluation_job_id')=?)) LIMIT 1",
                    (op[0],preparation,plan.evaluation_job_id)).fetchone()
                if shared:raise CancellationError()
                intent=_intent(db,plan)
                if intent is not None:
                    if intent.state!='OWNED_STOPPED':raise CancellationError()
                    targets.append(intent)
            # The batch canceled-cleanup journal already exists. Feed it only
            # submission plans owned by this canceled operation, using frozen
            # inventory and the same exclusive drain fence as single torrents.
            plans=db.execute(
                "SELECT DISTINCT s.plan_id FROM batch_torrent_submissions s "
                "JOIN batch_episode_reservations r ON r.plan_id=s.plan_id "
                "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
                "WHERE m.operation_id=? AND r.state='ACTIVE' "
                "ORDER BY s.plan_id",(op[0],)).fetchall()
            if len(plans)>1000:raise CancellationError()
            from src.nextgen.batch_cancellation_cleanup import load_cancelled_batch
            batches=[load_cancelled_batch(db,op[0],plan) for (plan,) in plans]
            result=(op[0],targets,batches)
        self._log(receipts)
        return result
    def cleanup(self,job_id,*,max_targets=1):
        if type(max_targets) is not int or not 1<=max_targets<=32:raise CancellationError()
        with self._admission():
            status=self.store.status(job_id)
            if not status['can_cleanup']:return status
            try:
                with OperationGate(self.database).hold(status['operation_id'],cleanup=True):
                    op,targets,batches=self._targets(job_id)
                    complete=True;processed=0
                    for target in targets:
                        with self.store.queue.connection() as db:
                            prior=db.execute('SELECT phase FROM cancellation_cleanup WHERE plan_id=?',(target.plan.plan_id,)).fetchone()
                        if prior==('COMPLETE',):continue
                        if processed>=max_targets:
                            complete=False;continue
                        processed+=1
                        complete=self._clean_target(op,target) and complete
                    if batches:
                        from src.nextgen.batch_cancellation_cleanup import BatchCanceledCleanup
                        batch_cleaner=BatchCanceledCleanup(self)
                        for target in batches:
                            with self.store.queue.connection() as db:
                                prior=db.execute(
                                    'SELECT phase FROM batch_cancellation_cleanup '
                                    'WHERE plan_id=?',(target.plan.plan_id,)).fetchone()
                            if prior==('COMPLETE',):continue
                            if processed>=max_targets:
                                complete=False;continue
                            processed+=1
                            complete=batch_cleaner._clean_target(op,target) and complete
                    if complete:
                        from src.nextgen.staging_artifacts import (
                            clean_temporaries, clean_published_batch,
                            reconcile_planned_batch,
                        )
                        self._fence()
                        reconcile_planned_batch(
                            self.store.queue,op,guard=self._fence,
                            keep_root=self.configuration.value('storage.keep_root'))
                        clean_published_batch(
                            self.store.queue,op,guard=self._fence,
                            keep_root=self.configuration.value('storage.keep_root'))
                        clean_temporaries(self.store.queue,op,guard=self._fence)
                    self._state(job_id,'COMPLETE' if complete else 'PENDING',
                                'CANCELLATION_COMPLETE' if complete else 'CANCELLATION_PENDING')
            except CleanupBusy:
                # Keep CANCEL_REQUESTED and leases intact until drain is proven.
                return self.store.status(job_id)
            except BatchStageCleanupRetry:
                # Use the existing worker retry policy; no new retry journal.
                self._state(job_id,'PENDING','CANCELLATION_PENDING',
                            cause='STAGING_REVIEW')
                return {**self.store.status(job_id),'staging_retry':True}
            except ClientUnavailable:
                self._state(job_id,'PENDING','CANCELLATION_PENDING',cause='DOWNLOAD_CLIENT_UNAVAILABLE')
            except (CancellationError,ClientInvalid,ClientAuthenticationFailed,ClientUnsupported,OSError,ValueError) as exc:
                from src.nextgen.reasons import get_reason
                cause=getattr(exc,'reason_code','STORAGE_UNAVAILABLE' if isinstance(exc,OSError) else 'CANCELLATION_REVIEW')
                self._state(job_id,'REVIEW','CANCELLATION_REVIEW',cause=cause if get_reason(cause) is not None else 'CANCELLATION_REVIEW')
            return self.store.status(job_id)
