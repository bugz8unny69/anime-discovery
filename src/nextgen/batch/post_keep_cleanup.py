"""After batch Keep, remove only staged files with confirmed Sonarr copies.

No release-path guesses, directory sweep or qB cleanup here. The existing
inode-fenced remove_selected helper handles each separate publication.
"""
import json

from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.keep_selection import KeepSelection
from src.nextgen.sonarr import Client, Options, KeepReview, KeepUnavailable, existing_file
from src.nextgen.staging import StagingReview
from src.nextgen.storage.batch_decisions import batch_staged
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.review_decisions import remove_selected
from src.nextgen.storage.sqlite import enqueue_job, transaction
from src.nextgen.storage.staging import Journal as StageJournal
from src.nextgen.history import integer


KIND='CLEANUP_KEPT_BATCH_STAGE'


def enqueue(db,claim):
    """Called only in successful batch KEEP_MEDIA completion transaction."""
    if not db.in_transaction or claim.kind!='KEEP_MEDIA':
        raise KeepReview()
    imports=db.execute(
        "SELECT plan_id,count(*),sum(CASE WHEN phase='COMPLETE' THEN 1 ELSE 0 END) "
        "FROM batch_keep_imports WHERE job_id=? GROUP BY plan_id",
        (claim.job_id,)).fetchall()
    if len(imports)!=1 or imports[0][1]<1 or imports[0][1]!=imports[0][2]:
        raise KeepReview()
    if db.execute(
        "SELECT 1 FROM batch_stage_cleanups WHERE keep_job_id=?",
        (claim.job_id,)).fetchone():
        raise KeepReview()
    now=__import__('time').time_ns()//1000000
    child=enqueue_job(
        db,kind=KIND,payload={'keep_job_id':claim.job_id},
        component='worker',event_id=claim.event_id,
        created_by_job_id=claim.job_id)
    db.execute(
        "INSERT INTO batch_stage_cleanups"
        "(job_id,keep_job_id,plan_id,phase,created_at_ms,updated_at_ms) "
        "VALUES(?,?,?,'PLANNED',?,?)",
        (child,claim.job_id,imports[0][0],now,now))
    return child


class Service:
    def __init__(self,configuration,secrets,*,client_factory=Client,
                 remove=remove_selected):
        self.configuration,self.secrets=configuration,secrets
        self.client_factory,self.remove=client_factory,remove
        self.queue=JobQueue(configuration.value('storage.database_path'))

    def facts(self,db,claim,keep_job):
        self.queue._owns(db,claim,self.queue.now())
        if claim.kind!=KIND:raise KeepReview()
        lineage=db.execute(
            "SELECT j.created_by_job_id,j.event_id,j.kind,o.state "
            "FROM jobs j JOIN job_operation_members m ON m.job_id=j.job_id "
            "JOIN job_operations o ON o.operation_id=m.operation_id "
            "WHERE j.job_id=?",(claim.job_id,)).fetchone()
        if lineage!=(keep_job,claim.event_id,KIND,'ACTIVE'):
            raise KeepReview()
        cleanup=db.execute(
            "SELECT keep_job_id,plan_id,phase FROM batch_stage_cleanups "
            "WHERE job_id=?",(claim.job_id,)).fetchone()
        if cleanup is None or cleanup[0]!=keep_job:raise KeepReview()
        control=db.execute(
            "SELECT target_job_id,operation_id,action FROM management_actions "
            "WHERE job_id=?",(keep_job,)).fetchone()
        completed=db.execute(
            "SELECT state,event_id FROM jobs WHERE job_id=?",(keep_job,)).fetchone()
        if control is None or control[2]!='KEEP' or completed!=('DONE',claim.event_id):
            raise KeepReview()
        if operation(db,control[0])[:2]!=(control[1],'STAGED'):
            raise KeepReview()
        staged=batch_staged(db,control[1])
        if any(row[1]!=cleanup[1] for row in staged):
            raise KeepReview()
        imports=db.execute(
            "SELECT file_index,phase,data_json FROM batch_keep_imports "
            "WHERE job_id=? AND plan_id=? ORDER BY file_index",
            (keep_job,cleanup[1])).fetchall()
        if (len(imports)!=len(staged) or
                {row[0] for row in imports}!={row[2] for row in staged}
                or any(row[1]!='COMPLETE' for row in imports)):
            raise KeepReview()
        source={row[2]:row for row in staged}
        return cleanup[2],tuple((source[i],json.loads(raw))
                                for i,phase,raw in imports)

    def run(self,claim,keep_job,cancelled):
        with StageJournal(self.queue.database).lock(claim):
            with self.queue.connection() as db,transaction(db):
                phase,files=self.facts(db,claim,keep_job)
            if phase=='COMPLETE':return True
            for row,data in files:
                if cancelled.is_set():raise KeepReview()
                _,plan,index,episode,manifest,receipts=row
                selection=KeepSelection(**data['selection'])
                options=Options(**data['options'])
                plan_doc=json.loads(manifest)
                proofs=json.loads(receipts)
                media=[e for e in plan_doc['entries'] if e['role']=='media']
                artifact=[p for p in proofs if p['role']=='media']
                if (len(media)!=1 or len(artifact)!=1
                        or selection.preparation_plan_id!=plan
                        or selection.tvdb_episode!=episode
                        or selection.media_relative_path!=media[0]['path']
                        or data['source_file']!=artifact[0]['file']
                        or data['source_parent']!=artifact[0]['root']
                        or plan_doc['root_identity']!=data['root_identity']):
                    raise KeepReview()
                client=self.client_factory(options,self.secrets.sonarr_api_key())
                series=client.series(selection.tvdb_series_id)
                if (not series or
                        (series.get('id'),series.get('path'))!=
                        (data['series_id'],data['series_path'])):
                    raise KeepReview()
                sonarr_episode=client.episode(selection,series)
                if (sonarr_episode.get('id')!=data['episode_id']
                        or not sonarr_episode.get('hasFile')):
                    raise KeepReview()
                result=data.get('result')
                if not isinstance(result,dict):raise KeepReview()
                record=client.request(
                    'episodefile/'+str(result['episode_file_id']))

                def guard():
                    if cancelled.is_set():raise KeepReview()
                    with self.queue.connection() as db,transaction(db):
                        self.facts(db,claim,keep_job)
                    if existing_file(options,series,sonarr_episode,record,
                                     data['source_file'][2])!=result:
                        raise KeepReview()

                guard()
                self.remove(manifest,receipts,guard,options.keep_root)
                guard()
            with self.queue.connection() as db,transaction(db):
                phase,files=self.facts(db,claim,keep_job)
                if phase=='PLANNED':
                    db.execute(
                        "UPDATE batch_stage_cleanups SET phase='COMPLETE',"
                        "updated_at_ms=? WHERE job_id=? AND phase='PLANNED'",
                        (self.queue.now(),claim.job_id))
            return True
