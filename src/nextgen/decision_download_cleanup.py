"""Independent owned-download cleanup after a completed Keep/Reject decision."""
import json

from src.nextgen.acquisition.cleanup import FileCleanup
from src.nextgen.acquisition.owned_cleanup import OwnedCleanup
from src.nextgen.acquisition.qbittorrent import Client
from src.nextgen.acquisition.submission import ClientUnavailable, SubmissionPlan, manifest_from_json
from src.nextgen.async_io import blocking
from src.nextgen.cancellation import CancellationError, CleanupBusy, OperationGate
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.messages import DEFAULT_CATALOG
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.review_decisions import staged
from src.nextgen.storage.sqlite import enqueue_job, transaction
from src.nextgen.storage.submissions import _intent

KIND='CLEANUP_DECIDED_DOWNLOAD'
DEFINITION=HandlerDefinition(KIND,'Remove completed decision download')
STOPPED_JOBS=('NEEDS_REVIEW','BLOCKED')


def status(db,decision):
    rows=db.execute("SELECT job_id,state,last_reason_code FROM jobs WHERE kind=? "
        "AND json_extract(payload_json,'$.decision_job_id')=? ORDER BY job_id",(KIND,decision)).fetchall()
    if not rows:return None
    if len(rows)!=1:raise CancellationError()
    job,state,reason=rows[0]
    return {'job_id':job,'state':state,'status':DEFAULT_CATALOG.job_status(state),'completed':state=='DONE',
        'completion':DEFAULT_CATALOG.reason('DECISION_DOWNLOAD_CLEANUP_COMPLETE') if state=='DONE' else None,
        'reason':None if reason is None else DEFAULT_CATALOG.reason(reason),'status_url':f'/api/v1/jobs/{job}'}


def enqueue(db,claim,decision):
    # Worker completion persists this inside the same transaction as DONE. No
    # historical decisions are backfilled or given new automatic delete authority.
    integer(decision,positive=True)
    if status(db,decision) is not None:raise CancellationError()
    enqueue_job(db,kind=KIND,payload={'decision_job_id':decision},component='worker',
        event_id=claim.event_id,created_by_job_id=claim.job_id)


class Service(OwnedCleanup):
    cleanup_event='DECISION_DOWNLOAD_CONTROL_RECORDED'
    complete_reason='DECISION_DOWNLOAD_CLEANUP_COMPLETE'
    pending_reason='DECISION_DOWNLOAD_CLEANUP_WAITING'

    def __init__(self,configuration,secrets,*,client_factory=Client,files_factory=FileCleanup):
        self.configuration,self.secrets=configuration,secrets
        self.queue=JobQueue(configuration.value('storage.database_path'))
        self.client_factory,self.files_factory=client_factory,files_factory
        self.component='worker'

    def _log(self,records):pass  # Durable history is committed by the shared journal.

    def facts(self,db):
        self.queue._owns(db,self.claim,self.queue.now())
        row=db.execute("SELECT a.operation_id,a.target_job_id,a.action,j.state,j.event_id "
            "FROM management_actions a JOIN jobs j USING(job_id) WHERE a.job_id=?",(self.decision,)).fetchone()
        if not row or row[2] not in ('KEEP','REJECT') or row[3]!='DONE' or row[4]!=self.claim.event_id:raise CancellationError()
        op,target,action,_,event=row
        origin=db.execute('SELECT created_by_job_id,event_id FROM jobs WHERE job_id=?',(self.claim.job_id,)).fetchone()
        if operation(db,target)[:2]!=(op,'STAGED') or operation(db,self.claim.job_id)[0]==op:raise CancellationError()
        source=staged(db,op)
        publication=json.loads(source[2]);protected=[publication['root']]
        if action=='KEEP':
            keep=db.execute('SELECT phase,data_json FROM keep_imports WHERE job_id=?',(self.decision,)).fetchone()
            if not keep or keep[0]!='COMPLETE':raise CancellationError()
            data=json.loads(keep[1]);cleanup=data.get('post_cleanup',{})
            if cleanup.get('state')!='COMPLETE':raise CancellationError()
            predecessor=cleanup.get('job_id')
            if db.execute('SELECT kind,state,created_by_job_id FROM jobs WHERE job_id=?',(predecessor,)).fetchone()!=('CLEANUP_KEPT_MEDIA','DONE',self.decision):raise CancellationError()
            protected.append(data['options']['keep_root'])
        else:
            if db.execute("SELECT operation_id,cleanup_state FROM anime_review_decisions WHERE job_id=? AND decision='REJECT'",(self.decision,)).fetchone()!=(op,'COMPLETE'):raise CancellationError()
            predecessor=self.decision
        if origin!=(predecessor,event) or status(db,self.decision)['job_id']!=self.claim.job_id:raise CancellationError()
        if db.execute("SELECT 1 FROM job_operation_members m JOIN jobs j USING(job_id) "
            "WHERE m.operation_id=? AND j.state NOT IN ('DONE','CANCELED') LIMIT 1",(op,)).fetchone():raise CancellationError()
        rows=db.execute('SELECT p.job_id,j.event_id,p.plan_id FROM acquisition_plans p JOIN jobs j ON j.job_id=p.job_id '
            'JOIN job_operation_members m ON m.job_id=p.job_id WHERE m.operation_id=?',(op,)).fetchall()
        if len(rows)!=1 or rows[0][2]!=source[1]:raise CancellationError()
        preparation,event,plan_id=rows[0]
        if event!=self.claim.event_id:raise CancellationError()
        # Read historical ownership only. The acquisition reader deliberately
        # rejects a rejected anime; cleanup must never relax that send fence.
        receipt=db.execute("SELECT p.submission_marker,p.info_hash,p.info_sha256,p.manifest_json,r.evaluation_job_id "
            "FROM acquisition_plans p JOIN episode_reservations r USING(reservation_id) JOIN jobs j ON j.job_id=p.job_id "
            "WHERE p.plan_id=? AND p.state='PREPARED' AND r.state='ACTIVE' AND j.state='DONE' "
            "AND j.kind='PREPARE_ACQUISITION' AND j.event_id=?",(plan_id,event)).fetchone()
        if receipt is None:raise CancellationError()
        plan=SubmissionPlan(preparation,plan_id,receipt[4],event,receipt[0],manifest_from_json(*receipt[1:4]))
        shared=db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id<>? AND "
            "((j.kind IN ('SUBMIT_TORRENT','DOWNLOAD_TORRENT') AND json_extract(j.payload_json,'$.preparation_job_id')=?) OR "
            "(j.kind IN ('RESERVE_EPISODE','PREPARE_ACQUISITION') AND json_extract(j.payload_json,'$.evaluation_job_id')=?)) LIMIT 1",
            (op,preparation,plan.evaluation_job_id)).fetchone()
        intent=_intent(db,plan)
        if shared or intent is None or intent.state!='OWNED_STOPPED':raise CancellationError()
        selected=plan.manifest.files[plan.manifest.selected_index]
        if publication['source_root']!=intent.options.download_root or publication['source']['path']!=selected.path or publication['source']['file'][2]!=selected.size:raise CancellationError()
        return op,intent,tuple(protected),publication['source']['root']

    def _capture(self,cleaner):
        captured=cleaner.capture()
        if captured['root']!=self.source_root_identity:raise CancellationError()
        return captured

    def _fence(self,db=None):
        if self.cancelled.is_set():raise CancellationError()
        if db is not None:self.facts(db)
        else:
            with self.queue.connection() as connection,transaction(connection):self.facts(connection)

    def run(self,claim,decision,cancelled):
        self.claim,self.decision,self.cancelled=claim,decision,cancelled
        self.guard=self._fence
        with self.queue.connection() as db,transaction(db):op,intent,protected,self.source_root_identity=self.facts(db)
        with OperationGate(self.queue.database).hold(op,cleanup=True):
            self._fence()
            factory=self.files_factory
            self.files_factory=lambda target,roots:factory(target,(*roots,*protected))
            return self._clean_target(op,intent)


def _persist(db,claim,value):
    row=db.execute('SELECT c.phase FROM cancellation_cleanup c JOIN staging_publications s USING(plan_id) '
        'JOIN job_operation_members m ON m.job_id=s.job_id JOIN management_actions a ON a.operation_id=m.operation_id '
        'WHERE a.job_id=? AND c.operation_id=a.operation_id',(value,)).fetchall()
    if row!=[('COMPLETE',)]:raise CompletionRejected(Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW'))


def registration(secrets,*,service_factory=Service):
    async def execute(context):
        try:
            payload=context.data()
            if set(payload)!={'decision_job_id'}:raise ValueError()
            decision=integer(payload['decision_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:done=await blocking(service_factory(context.configuration,secrets).run,context.claim,decision,context.cancelled)
        except CleanupBusy:return Outcome('defer','DECISION_DOWNLOAD_CLEANUP_WAITING',delay_ms=1000)
        except ClientUnavailable:return Outcome('retry','DECISION_DOWNLOAD_CLEANUP_UNAVAILABLE')
        except OSError:return Outcome('retry','DECISION_DOWNLOAD_CLEANUP_UNAVAILABLE')
        except (ValueError,KeyError,TypeError):return Outcome('review','DECISION_DOWNLOAD_CLEANUP_REVIEW')
        if not done:return Outcome('defer','DECISION_DOWNLOAD_CLEANUP_WAITING',delay_ms=30000)
        return Outcome(value=decision)
    return Registration(KIND,DEFINITION,execute,persist=_persist)
