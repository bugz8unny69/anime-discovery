"""Explicit management actions, never arbitrary HTTP-supplied job kinds.

Caller holds maintenance admission. Each action has a separate control scope;
its target scope may be canceled/staged without canceling the control job.
"""
from contextlib import ExitStack
from src.nextgen.cancellation import CleanupBusy, OperationGate
from src.nextgen.history import append_job_history, integer
from src.nextgen.messages import MessageCatalog
from src.nextgen.storage.cancellation import CancellationStore, operation, unfinished_resources
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import enqueue_job_with_receipt, transaction

KINDS={'KEEP':'KEEP_MEDIA','CLEANUP':'CLEANUP_CANCELED_OPERATION'}
CATALOG=MessageCatalog()


class ActionUnavailable(ValueError):
    reason_code='MANAGEMENT_ACTION_UNAVAILABLE'
    def __init__(self):super().__init__('This action is not available for this work.')


class ActionNotFound(ActionUnavailable):
    reason_code='API_ROUTE_NOT_FOUND'


def target(db,job_id):
    integer(job_id,positive=True)
    if not db.execute('SELECT 1 FROM jobs WHERE job_id=?',(job_id,)).fetchone():raise ActionNotFound()
    if db.execute('SELECT 1 FROM management_actions WHERE job_id=?',(job_id,)).fetchone():raise ActionUnavailable()
    return operation(db,job_id)


def disabled_reason(state,reason_code=None):
    # Presentation only: never changes scheduling or authorizes an action.
    code={'PENDING':'MANAGEMENT_JOB_QUEUED','RUNNING':'MANAGEMENT_JOB_RUNNING',
          'RETRY_WAIT':'MANAGEMENT_JOB_WAITING','DONE':'MANAGEMENT_JOB_COMPLETE',
          'CANCELED':'MANAGEMENT_JOB_CANCELED'}.get(state)
    if code is None:
        code=reason_code or ('MANAGEMENT_JOB_ATTENTION' if state in
                            ('ON_HOLD','BLOCKED','NEEDS_REVIEW') else 'MANAGEMENT_ACTION_UNAVAILABLE')
    return CATALOG.reason(code)


def receipt(db,job_id,*,reused=False):
    row=db.execute('SELECT state,activity_code,last_reason_code FROM jobs WHERE job_id=?',(job_id,)).fetchone()
    data={'job_id':job_id,'state':row[0],'status':CATALOG.job_status(row[0],row[1]),
            'reason':None if row[2] is None else CATALOG.reason(row[2]),
            'status_url':f'/api/v1/jobs/{job_id}','history_url':f'/api/v1/jobs/{job_id}/history',
            'notification':CATALOG.reason('MANAGEMENT_JOB_EXISTS' if reused else 'MANAGEMENT_JOB_SUBMITTED'),
            'reused':reused,'disable_action':True,
            'disabled_reason':disabled_reason(row[0],row[2])}
    if db.execute("SELECT 1 FROM management_actions WHERE job_id=? AND action='KEEP'",(job_id,)).fetchone():
        data['execution_available']=False
        data['availability_reason']=CATALOG.reason('KEEP_NOT_READY')
    return data


class ManagementActions:
    def __init__(self,database):
        self.queue=JobQueue(database)
        self.cancellations=CancellationStore(database)

    def submit(self,job_id,action):
        if action not in ('keep','cancel','cleanup'):raise ActionUnavailable()
        records=[]
        with ExitStack() as locks,self.queue.connection() as db,transaction(db):
            op=target(db,job_id)
            selected='KEEP' if action=='keep' else 'CLEANUP'
            prior=db.execute('SELECT job_id FROM management_actions WHERE operation_id=? AND action=?',
                             (op[0],selected)).fetchone()
            if prior:
                state=db.execute('SELECT state FROM jobs WHERE job_id=?',(prior[0],)).fetchone()[0]
                if action=='cleanup' and state in ('NEEDS_REVIEW','BLOCKED'):
                    now=self.queue.now()
                    db.execute("UPDATE jobs SET state='PENDING',available_at_ms=?,last_reason_code=NULL,activity_code=NULL,updated_at_ms=? WHERE job_id=?",(now,now,prior[0]))
                    records.append(append_job_history(db,job_id=prior[0],event_code='MANAGEMENT_ACTION_RESUMED',component='api',occurred_at_ms=now))
                    data=receipt(db,prior[0]);data['resumed']=True
                    return 202,data,tuple(records)
                return 202,receipt(db,prior[0],reused=True),()
            now=self.queue.now()
            if action=='keep':
                if op[1]!='STAGED':raise ActionUnavailable()
            else:
                if action=='cancel':
                    _,audits=self.cancellations.request_in_transaction(db,job_id)
                    records.extend(audits)
                    op=operation(db,job_id)
                    now=self.queue.now()
                if op[1] not in ('CANCEL_REQUESTED','CANCELED'):raise ActionUnavailable()
                if op[2]=='COMPLETE':return 200,{'completed':True,'disable_action':True,
                                                 'notification':CATALOG.reason('CANCELLATION_COMPLETE')},tuple(records)
                running=db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) "
                                   "WHERE m.operation_id=? AND j.state='RUNNING' LIMIT 1",(op[0],)).fetchone()
                drained=False
                if not running and not unfinished_resources(db,op[0]):
                    # Expired/recovered DB state alone is not proof of drainage.
                    # Nonblocking lock also catches stale handlers still in I/O.
                    try:locks.enter_context(OperationGate(self.queue.database).hold(op[0],cleanup=True))
                    except CleanupBusy:pass
                    else:drained=True
                if drained:
                    db.execute("UPDATE job_operations SET state='CANCELED',cleanup_state='COMPLETE',"
                               "reason_code='CANCELLATION_COMPLETE',updated_at_ms=? WHERE operation_id=?",(now,op[0]))
                    records.append(append_job_history(db,job_id=job_id,event_code='CANCELLATION_CLEANUP_CHANGED',
                        reason_code='CANCELLATION_COMPLETE',component='api',occurred_at_ms=now))
                    return 200,{'completed':True,'disable_action':True,
                                'notification':CATALOG.reason('CANCELLATION_COMPLETE')},tuple(records)
            event=db.execute('SELECT event_id FROM jobs WHERE job_id=?',(job_id,)).fetchone()[0]
            control,audit=enqueue_job_with_receipt(db,component='api',kind=KINDS[selected],event_id=event,
                payload={'target_job_id':job_id},available_at_ms=now)
            db.execute('INSERT INTO management_actions VALUES(?,?,?,?,?)',(op[0],selected,job_id,control,now))
            records.append(audit)
            data=receipt(db,control)
        return 202,data,tuple(records)

    def capabilities(self,db,job_id):
        # Read using caller's snapshot. No mutations or nested connection.
        control=db.execute('SELECT action FROM management_actions WHERE job_id=?',(job_id,)).fetchone()
        if control:
            return {name:{'enabled':False,'disabled_reason':CATALOG.reason('MANAGEMENT_ACTION_UNAVAILABLE')}
                    for name in ('keep','cancel','cleanup')}
        op=operation(db,job_id)
        members=db.execute('SELECT state FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id=?',(op[0],)).fetchall()
        from src.nextgen.storage.cancellation import CANCELABLE
        cancelable=op[1]=='ACTIVE' and (any(r[0] in CANCELABLE for r in members) or unfinished_resources(db,op[0]))
        # An action job in this scope disables competing buttons as well.
        # Held/review/blocked jobs are not described as still running.
        busy=db.execute("SELECT j.state,j.last_reason_code FROM management_actions a JOIN jobs j USING(job_id) "
                        "WHERE a.operation_id=? AND j.state IN ('PENDING','RUNNING','RETRY_WAIT') "
                        "ORDER BY CASE j.state WHEN 'RUNNING' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,j.job_id LIMIT 1",
                        (op[0],)).fetchone()
        result={}
        for name,enabled in (('keep',op[1]=='STAGED'),('cancel',cancelable),
                             ('cleanup',op[1] in ('CANCEL_REQUESTED','CANCELED') and op[2]!='COMPLETE')):
            code='KEEP' if name=='keep' else 'CLEANUP'
            row=db.execute('SELECT job_id FROM management_actions WHERE operation_id=? AND action=?',(op[0],code)).fetchone()
            resumable=name=='cleanup' and row is not None and db.execute('SELECT state FROM jobs WHERE job_id=?',(row[0],)).fetchone()[0] in ('NEEDS_REVIEW','BLOCKED')
            allowed=bool(enabled and (row is None or resumable) and busy is None)
            job=None if row is None else receipt(db,row[0],reused=True)
            reason=None
            if not allowed:
                reason=(disabled_reason(*busy) if busy is not None else
                        CATALOG.reason('KEEP_NOT_READY') if name=='keep' and row is None else
                        job['disabled_reason'] if job is not None else
                        CATALOG.reason('MANAGEMENT_ACTION_UNAVAILABLE'))
            result[name]={'enabled':allowed,'disabled_reason':reason,'job':job}
        result['keep']['execution_available']=False
        result['keep']['availability_reason']=CATALOG.reason('KEEP_NOT_READY')
        return result

    def bind(self,claim,action):
        with self.queue.connection() as db,transaction(db):
            self.queue._owns(db,claim,self.queue.now())
            data=claim.data()
            if set(data)!={'target_job_id'}:raise ActionUnavailable()
            integer(data['target_job_id'],positive=True)
            row=db.execute('SELECT target_job_id,operation_id FROM management_actions WHERE job_id=? AND action=?',
                           (claim.job_id,action)).fetchone()
            if row is None or row[0]!=data['target_job_id'] or claim.kind!=KINDS[action]:raise ActionUnavailable()
            if operation(db,claim.job_id)[0]==row[1]:raise ActionUnavailable()
            op=operation(db,row[0])
            if op[0]!=row[1] or (op[1]!='STAGED' if action=='KEEP' else op[1] not in ('CANCEL_REQUESTED','CANCELED')):
                raise ActionUnavailable()
            return row[0]
