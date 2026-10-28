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
                if op[2]!='COMPLETE':
                    from src.nextgen.storage.sonarr_candidates import schedule_after_cleanup
                    records+=schedule_after_cleanup(db,op[0])
        self._log(records)
    @staticmethod
    def _empty_magnet_root(path,marker):
        """Never authorize torrent cleanup over unknown local files."""
        import os
        from pathlib import PurePosixPath
        from src.nextgen.acquisition.cleanup import directory
        if PurePosixPath(path).name!='ad-'+marker:raise CancellationError()
        try:
            with directory(path) as fd:
                with os.scandir(fd) as rows:
                    return next(rows,None) is None
        except FileNotFoundError:
            return True

    def _pre_manifest(self,operation_id):
        """Resolve old magnet intents without inventing a .torrent file list.

        No files: remove an exact-owned qB torrent, never local files. A missing
        torrent must be absent past the metadata deadline and have no files in
        its isolated root. A pre-send external torrent remains untouched.
        """
        from src.nextgen.storage.sonarr_magnet_intake import _prior
        with self.store.queue.connection() as db:
            rows=db.execute(
                "SELECT i.event_id,i.created_at_ms FROM sonarr_magnet_intents i "
                "JOIN job_operation_members m ON m.job_id=i.job_id "
                "WHERE m.operation_id=? AND i.state<>'EXTERNAL' AND NOT EXISTS "
                "(SELECT 1 FROM acquisition_plans p "
                "JOIN torrent_submissions s USING(plan_id) "
                "WHERE p.job_id=i.job_id AND p.submission_marker=i.marker "
                "AND p.info_hash=i.info_hash AND s.state='OWNED_STOPPED')",
                (operation_id,)).fetchall()
            intents=[(_prior(db,event),created) for event,created in rows]
        if len(intents)>32:raise CancellationError()
        if not intents:return set(),True
        credentials=self.secrets.qbittorrent_credentials()
        settled=set()
        for intent,created in intents:
            self._fence()
            client=self.client_factory(intent.options,credentials)
            client.login()
            observed=client.inspect(intent.info_hash)
            if observed is None:
                # An uncertain add can arrive late. Don't declare it absent
                # just because its first HTTP read raced qBittorrent's add.
                if self.queue.now()-created<600000:
                    return settled,False
                if not self._empty_magnet_root(intent.options.download_root,
                                               intent.marker):
                    raise CancellationError()
                settled.add(intent.event_id)
                continue
            if (observed.info_hash!=intent.info_hash
                    or observed.save_path.rstrip('/')!=intent.options.download_root
                    or observed.category!=intent.options.category
                    or observed.auto_tmm is not False
                    or 'ad-'+intent.marker not in observed.tags
                    or any(t.startswith('ad-') and t!='ad-'+intent.marker
                           for t in observed.tags)
                    or observed.files
                    or not self._empty_magnet_root(intent.options.download_root,
                                                   intent.marker)):
                raise CancellationError()
            # REVIEW means an earlier command was uncertain or ownership was
            # disputed; never send a second destructive request on replay.
            if intent.state=='REVIEW':raise CancellationError()
            with self.store.queue.connection() as db,transaction(db):
                self._fence(db)
                changed=db.execute(
                    "UPDATE sonarr_magnet_intents SET state='REVIEW',"
                    "updated_at_ms=? WHERE event_id=? AND state=?",
                    (self.queue.now(),intent.event_id,intent.state)).rowcount
                if changed!=1:raise CancellationError()
            if observed.state not in ('pausedDL','pausedUP','stoppedDL','stoppedUP'):
                client.stop_legacy_metadata(intent)
            if not client.remove_empty_legacy_magnet(intent):
                return settled,False
            settled.add(intent.event_id)
        return settled,True

    def _targets(self,job_id,*,resolved=()):
        with self.store.queue.connection() as db,transaction(db):
            self._fence(db)
            op=operation(db,job_id)
            if op[1] not in ('CANCEL_REQUESTED','CANCELED'):raise CancellationError()
            receipts=[];now=self.store.queue.now()
            # Exclusive OperationGate proves participating handlers have drained.
            for (member,) in db.execute('SELECT job_id FROM job_operation_members WHERE operation_id=?',(op[0],)).fetchall():
                receipts.extend(cancel_job(db,member,now,self.component))
            # Unpromoted admissions lack an inventory for bounded cleanup.
            # Promoted admissions use the existing exact-owned cleanup below;
            # unresolved admissions must retain their reservation.
            pending=db.execute(
                "SELECT i.event_id FROM sonarr_magnet_intents i "
                "JOIN job_operation_members m ON m.job_id=i.job_id "
                "WHERE m.operation_id=? AND i.state<>'EXTERNAL' AND NOT EXISTS "
                "(SELECT 1 FROM acquisition_plans p JOIN torrent_submissions s USING(plan_id) "
                "WHERE p.job_id=i.job_id AND p.submission_marker=i.marker "
                "AND p.info_hash=i.info_hash AND s.state='OWNED_STOPPED')",(op[0],)).fetchall()
            if any(event not in resolved for (event,) in pending):
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
                    resolved,ready=self._pre_manifest(status['operation_id'])
                    if not ready:
                        self._state(job_id,'PENDING','CANCELLATION_PENDING')
                        return self.store.status(job_id)
                    op,targets,batches=self._targets(job_id,resolved=resolved)
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
