"""Remove selected staging artifacts after rechecking a completed Sonarr Keep."""
import json

from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.history import integer
from src.nextgen.job_contracts import Outcome, Registration
from src.nextgen.keep_selection import KeepSelection, KeepSelectionInvalid
from src.nextgen.sonarr import Client, Options, KeepReview, KeepUnavailable, existing_file
from src.nextgen.staging import StagingReview, StagingBusy
from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.staging import Journal as StageJournal
from src.nextgen.storage.sqlite import enqueue_job, transaction
from src.nextgen.storage.review_decisions import staged, remove_selected
from src.nextgen.storage.cancellation import operation

KIND='CLEANUP_KEPT_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Remove kept episode from staging')


def enqueue(db,claim):
    """Called only inside the successful Keep completion transaction."""
    row=db.execute('SELECT phase,data_json FROM keep_imports WHERE job_id=?',(claim.job_id,)).fetchone()
    if not row or row[0]!='COMPLETE':raise KeepReview()
    data=json.loads(row[1])
    if 'post_cleanup' in data:raise KeepReview()
    job=enqueue_job(db,kind=KIND,payload={'keep_job_id':claim.job_id},component='worker',
        event_id=claim.event_id,created_by_job_id=claim.job_id)
    data['post_cleanup']={'job_id':job,'state':'PENDING'}
    raw=json.dumps(data,sort_keys=True,allow_nan=False)
    if len(raw.encode())>65536:raise KeepReview()
    db.execute('UPDATE keep_imports SET data_json=? WHERE job_id=?',(raw,claim.job_id))


def status(db,keep_job):
    row=db.execute('SELECT data_json FROM keep_imports WHERE job_id=?',(keep_job,)).fetchone()
    if row is None:return None
    record=json.loads(row[0]).get('post_cleanup')
    if record is None:return None
    row=db.execute('SELECT state,last_reason_code FROM jobs WHERE job_id=?',(record['job_id'],)).fetchone()
    if row is None:raise KeepReview()
    from src.nextgen.messages import DEFAULT_CATALOG
    return {'job_id':record['job_id'],'state':row[0],'status':DEFAULT_CATALOG.job_status(row[0]),
        'completed':record['state']=='COMPLETE',
        'completion':DEFAULT_CATALOG.reason('POST_KEEP_CLEANUP_COMPLETE') if record['state']=='COMPLETE' else None,
        'reason':None if row[1] is None else DEFAULT_CATALOG.reason(row[1]),
        'status_url':f"/api/v1/jobs/{record['job_id']}"}


class Service:
    def __init__(self,configuration,secrets,*,client_factory=Client,remove=remove_selected):
        self.configuration,self.secrets=configuration,secrets
        self.queue=JobQueue(configuration.value('storage.database_path'))
        self.client_factory,self.remove=client_factory,remove

    def facts(self,db,claim,keep):
        self.queue._owns(db,claim,self.queue.now())
        origin=db.execute('SELECT created_by_job_id,event_id FROM jobs WHERE job_id=?',(claim.job_id,)).fetchone()
        row=db.execute("SELECT k.phase,k.data_json,a.target_job_id,a.operation_id,j.state,j.event_id "
            "FROM keep_imports k JOIN management_actions a USING(job_id) JOIN jobs j USING(job_id) "
            "WHERE k.job_id=? AND a.action='KEEP'",(keep,)).fetchone()
        if not row or row[0]!='COMPLETE' or row[4]!='DONE' or origin!=(keep,row[5]) or claim.event_id!=row[5]:raise KeepReview()
        data=json.loads(row[1]);cleanup=data.get('post_cleanup')
        if not cleanup or cleanup.get('job_id')!=claim.job_id or cleanup.get('state') not in ('PENDING','COMPLETE'):raise KeepReview()
        if operation(db,row[2])[:2]!=(row[3],'STAGED'):raise KeepReview()
        source=staged(db,row[3]);selection=KeepSelection(**data['selection'])
        plan=json.loads(source[2]);proofs=json.loads(source[3])
        if (len(plan['entries'])!=3 or len(proofs)!=3
                or {p['role'] for p in proofs}!={'media','episode','series'}
                or [p['role'] for p in proofs]!=[p['role'] for p in plan['entries']]):raise KeepReview()
        media=[p for p in proofs if p['role']=='media']
        if (source[1]!=selection.preparation_plan_id or plan['root']!=selection.staging_root
                or plan['root_identity']!=data['root_identity'] or len(media)!=1
                or media[0]['path']!=selection.media_relative_path or media[0]['file']!=data['source_file']
                or media[0]['root']!=data['source_parent']):raise KeepReview()
        return data,source

    def run(self,claim,keep,cancelled):
        # Serialize recovered attempts without locking an entire anime.
        with StageJournal(self.queue.database).lock(claim):
            with self.queue.connection() as db,transaction(db):data,source=self.facts(db,claim,keep)
            if data['post_cleanup']['state']=='COMPLETE':return
            options=Options(**data['options']);selection=KeepSelection(**data['selection'])
            client=self.client_factory(options,self.secrets.sonarr_api_key())
            series=client.series(selection.tvdb_series_id)
            if not series or (series.get('id'),series.get('path'))!=(data['series_id'],data['series_path']):raise KeepReview()
            episode=client.episode(selection,series)
            if episode.get('id')!=data['episode_id'] or not episode.get('hasFile'):raise KeepReview()
            record=client.request('episodefile/'+str(data['result']['episode_file_id']))
            def guard():
                if cancelled.is_set():raise KeepReview()
                with self.queue.connection() as db,transaction(db):self.facts(db,claim,keep)
                # Recheck the permanent regular file before each source unlink.
                # No hash or byte-for-byte readback is performed.
                if existing_file(options,series,episode,record,data['source_file'][2])!=data['result']:raise KeepReview()
            guard()
            self.remove(source[2],source[3],guard,options.keep_root)
            guard()
            with self.queue.connection() as db,transaction(db):
                data,_=self.facts(db,claim,keep)
                data['post_cleanup']['state']='COMPLETE'
                db.execute('UPDATE keep_imports SET data_json=?,updated_at_ms=? WHERE job_id=?',
                    (json.dumps(data,sort_keys=True,allow_nan=False),self.queue.now(),keep))


def _persist(db,claim,value):
    row=db.execute('SELECT phase,data_json FROM keep_imports WHERE job_id=?',(value['keep_job_id'],)).fetchone()
    if not row or row[0]!='COMPLETE':raise KeepReview()
    record=json.loads(row[1]).get('post_cleanup')
    if record!={'job_id':claim.job_id,'state':'COMPLETE'}:raise KeepReview()
    from src.nextgen.decision_download_cleanup import enqueue as enqueue_download_cleanup
    enqueue_download_cleanup(db,claim,value['keep_job_id'])
    if value['refresh']:
        from src.nextgen.jobs.refresh_jellyfin_job import enqueue as enqueue_refresh
        enqueue_refresh(db,claim)


def registration(secrets,*,service_factory=Service):
    async def execute(context):
        try:
            payload=context.data()
            if set(payload)!={'keep_job_id'}:raise ValueError()
            keep=integer(payload['keep_job_id'],positive=True)
        except (ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        try:await blocking(service_factory(context.configuration,secrets).run,context.claim,keep,context.cancelled)
        except StagingBusy:return Outcome('defer','POST_KEEP_CLEANUP_WAITING',delay_ms=1000)
        except KeepUnavailable:return Outcome('retry','POST_KEEP_CLEANUP_UNAVAILABLE')
        except (KeepReview,StagingReview,MediaInvalid,KeepSelectionInvalid,ValueError,KeyError,TypeError):
            return Outcome('review','POST_KEEP_CLEANUP_REVIEW')
        except FileNotFoundError:return Outcome('review','POST_KEEP_CLEANUP_REVIEW')
        except OSError:return Outcome('retry','POST_KEEP_CLEANUP_UNAVAILABLE')
        return Outcome(value={'keep_job_id':keep,'refresh':bool(context.configuration.value('jellyfin.base_url'))})
    return Registration(KIND,DEFINITION,execute,persist=_persist)
