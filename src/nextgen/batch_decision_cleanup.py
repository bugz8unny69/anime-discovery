"""Conservative batch owned-torrent cleanup after completed Keep/Reject.

Reuse the existing single-use stop/remove and fd-relative manifest-only file
cleaner, but with its own durable v38 journal keyed by batch plan. The
adapter below is constructed exclusively from verified DB and torrent facts.
"""
import json
from types import SimpleNamespace

from src.nextgen.acquisition.cleanup import FileCleanup
from src.nextgen.acquisition.owned_cleanup import OwnedCleanup
from src.nextgen.acquisition.qbittorrent import Client
from src.nextgen.cancellation import CancellationError
from src.nextgen.history import append_job_history, job_attempt, integer
from src.nextgen.storage.batch_acquisition_candidate import _candidate
from src.nextgen.storage.batch_submission_journal import _intent
from src.nextgen.storage.batch_keep_imports import batch_publications
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction


def batch_cleanup_intent(intent):
    """Trusted, immutable-looking adapter for existing safe cleanup APIs."""
    return SimpleNamespace(
        options=intent.options,fingerprint=intent.fingerprint,
        plan=SimpleNamespace(
            plan_id=intent.candidate.plan_id,
            preparation_job_id=intent.candidate.reservation_job_id,
            marker=intent.marker,
            manifest=SimpleNamespace(
                info_hash=intent.inventory.info_hash,
                files=intent.inventory.files)))


class BatchDecisionCleanup(OwnedCleanup):
    cleanup_event='DECISION_DOWNLOAD_CONTROL_RECORDED'
    complete_reason='DECISION_DOWNLOAD_CLEANUP_COMPLETE'
    pending_reason='DECISION_DOWNLOAD_CLEANUP_WAITING'

    def __init__(self,configuration,secrets,*,client_factory=Client,
                 files_factory=FileCleanup):
        self.configuration,self.secrets=configuration,secrets
        self.queue=JobQueue(configuration.value('storage.database_path'))
        self.client_factory,self.files_factory=client_factory,files_factory
        self.component='worker'
        self.guard=self._fence
        self.claim=None
        self.decision=None

    def _log(self,records):
        pass  # Audit receipts are committed by the shared journal.

    def facts(self,db):
        self.queue._owns(db,self.claim,self.queue.now())
        row=db.execute(
            "SELECT a.operation_id,a.target_job_id,a.action,j.state,j.event_id "
            "FROM management_actions a JOIN jobs j USING(job_id) "
            "WHERE a.job_id=?",(self.decision,)).fetchone()
        if row is None or row[2] not in ('KEEP','REJECT') or row[3]!='DONE':
            raise CancellationError()
        op,target,action,_,event=row
        parent=db.execute(
            'SELECT created_by_job_id,event_id,kind FROM jobs WHERE job_id=?',
            (self.claim.job_id,)).fetchone()
        if event!=self.claim.event_id or parent[1:]!=(event,'CLEANUP_BATCH_DOWNLOAD'):
            raise CancellationError()
        if action=='KEEP':
            prior=db.execute(
                "SELECT b.phase,j.kind,j.state,b.decision_job_id "
                "FROM batch_keep_cleanup b JOIN jobs j ON j.job_id=b.job_id "
                "WHERE b.job_id=?",(parent[0],)).fetchone()
            if prior!=('COMPLETE','CLEANUP_BATCH_KEPT_MEDIA','DONE',self.decision):
                raise CancellationError()
        elif parent[0]!=self.decision:
            raise CancellationError()
        if operation(db,target)[:2]!=(op,'STAGED'):
            raise CancellationError()
        staged=batch_publications(db,op)
        if action=='KEEP':
            states=db.execute(
                'SELECT file_index,phase FROM batch_keep_imports '
                'WHERE job_id=? ORDER BY file_index',(self.decision,)).fetchall()
            if states!=[(item[1],'COMPLETE') for item in staged]:
                raise CancellationError()
        else:
            decided=db.execute(
                "SELECT cleanup_state FROM anime_review_decisions "
                "WHERE job_id=? AND operation_id=? AND decision='REJECT'",
                (self.decision,op)).fetchone()
            if decided!=('COMPLETE',):raise CancellationError()
        plan=staged[0][0]
        source=db.execute(
            "SELECT s.reservation_job_id,s.info_hash,s.info_sha256,s.state "
            "FROM batch_torrent_submissions s WHERE s.plan_id=?",
            (plan,)).fetchone()
        if source is None or source[3]!='OWNED_STOPPED':raise CancellationError()
        return op,plan,source[0],source[1],source[2]

    def _fence(self,db=None):
        if db is not None:
            return self.facts(db)
        with self.queue.connection() as connection,transaction(connection):
            return self.facts(connection)

    def source_hash(self,claim,decision):
        integer(decision,positive=True)
        self.claim,self.decision=claim,decision
        with self.queue.connection() as db,transaction(db):
            return self.facts(db)[3]

    def _journal(self,op,intent):
        with self.queue.connection() as db,transaction(db):
            self._fence(db)
            row=db.execute(
                'SELECT operation_id,decision_job_id,fingerprint,files_json,phase '
                'FROM batch_download_cleanup WHERE plan_id=?',
                (intent.plan.plan_id,)).fetchone()
            if row is not None:
                if row[:3]!=(op,self.decision,intent.fingerprint):
                    raise CancellationError()
                return json.loads(row[3]),row[4]
            now=self.queue.now()
            db.execute(
                "INSERT INTO batch_download_cleanup(plan_id,decision_job_id,"
                "operation_id,fingerprint,files_json,phase,created_at_ms,updated_at_ms)"
                " VALUES(?,?,?,?,?,'PREPARED',?,?)",
                (intent.plan.plan_id,self.decision,op,intent.fingerprint,'{}',now,now))
            return {},'PREPARED'

    def _advance(self,intent,prior,phase,files=None):
        with self.queue.connection() as db,transaction(db):
            self._fence(db)
            now=self.queue.now()
            if files is None:
                changed=db.execute(
                    'UPDATE batch_download_cleanup SET phase=?,updated_at_ms=? '
                    'WHERE plan_id=? AND decision_job_id=? AND phase=?',
                    (phase,now,intent.plan.plan_id,self.decision,prior)).rowcount
            else:
                raw=json.dumps(files,sort_keys=True,separators=(',',':'),allow_nan=False)
                if len(raw.encode())>1048576:raise CancellationError()
                changed=db.execute(
                    'UPDATE batch_download_cleanup SET phase=?,files_json=?,updated_at_ms=? '
                    'WHERE plan_id=? AND decision_job_id=? AND phase=?',
                    (phase,raw,now,intent.plan.plan_id,self.decision,prior)).rowcount
            if changed!=1:raise CancellationError()
            audit=append_job_history(
                db,job_id=self.claim.job_id,event_code=self.cleanup_event,
                reason_code=self.complete_reason if phase=='COMPLETE' else self.pending_reason,
                component='worker',occurred_at_ms=now,
                details={'attempt':job_attempt(db,self.claim.job_id)})
        self._log((audit,))

    def run(self,claim,decision,inventory,cancelled):
        self.claim,self.decision=claim,decision
        if cancelled.is_set():raise CancellationError()
        with self.queue.connection() as db,transaction(db):
            op,plan,reservation,digest,sha=self.facts(db)
            if (inventory.info_hash,inventory.info_sha256)!=(digest,sha):
                raise CancellationError()
            candidate=_candidate(db,reservation,inventory)
            if candidate.plan_id!=plan:raise CancellationError()
            source=_intent(db,candidate,inventory)
            if source is None or source.state!='OWNED_STOPPED':
                raise CancellationError()
            adapter=batch_cleanup_intent(source)
        if cancelled.is_set():raise CancellationError()
        return self._clean_target(op,adapter)
