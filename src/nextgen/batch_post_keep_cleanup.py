"""Exact post-Keep cleanup of all batch staging copies after Sonarr proof."""
import json

from src.nextgen.acquisition.media import MediaInvalid
from src.nextgen.cancellation import CancellationError
from src.nextgen.keep_selection import KeepSelection, KeepSelectionInvalid
from src.nextgen.sonarr import Client, Options, KeepReview, KeepUnavailable, existing_file
from src.nextgen.staging import StagingReview
from src.nextgen.storage.batch_keep_imports import batch_publications
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.review_decisions import remove_selected
from src.nextgen.storage.sqlite import transaction


class BatchPostKeepCleanup:
    def __init__(self,configuration,secrets,*,client_factory=Client,
                 remove=remove_selected):
        self.configuration,self.secrets=configuration,secrets
        self.queue=JobQueue(configuration.value('storage.database_path'))
        self.client_factory,self.remove=client_factory,remove

    def facts(self,db,claim,decision):
        self.queue._owns(db,claim,self.queue.now())
        origin=db.execute(
            'SELECT created_by_job_id,event_id,kind FROM jobs WHERE job_id=?',
            (claim.job_id,)).fetchone()
        row=db.execute(
            "SELECT a.operation_id,a.target_job_id,j.state,j.event_id "
            "FROM management_actions a JOIN jobs j USING(job_id) "
            "WHERE a.job_id=? AND a.action='KEEP'",
            (decision,)).fetchone()
        if (origin!=(decision,claim.event_id,'CLEANUP_BATCH_KEPT_MEDIA')
                or row is None or row[2:]!=('DONE',claim.event_id)
                or operation(db,row[1])[:2]!=(row[0],'STAGED')):
            raise KeepReview()
        published=batch_publications(db,row[0])
        keep=db.execute(
            "SELECT file_index,phase,data_json FROM batch_keep_imports "
            "WHERE job_id=? ORDER BY file_index",(decision,)).fetchall()
        if [x[0] for x in keep]!=[x[1] for x in published] or any(
                x[1]!='COMPLETE' for x in keep):
            raise KeepReview()
        return published,keep

    def run(self,claim,decision,cancelled):
        with self.queue.connection() as db,transaction(db):
            published,keep=self.facts(db,claim,decision)
            state=db.execute(
                'SELECT decision_job_id,phase FROM batch_keep_cleanup WHERE job_id=?',
                (claim.job_id,)).fetchone()
            if state is None:
                db.execute(
                    "INSERT INTO batch_keep_cleanup(job_id,decision_job_id,phase,"
                    "created_at_ms,updated_at_ms) VALUES(?,?,'PENDING',?,?)",
                    (claim.job_id,decision,self.queue.now(),self.queue.now()))
            elif state!=(decision,'PENDING') and state!=(decision,'COMPLETE'):
                raise KeepReview()
            else:
                if state[1]=='COMPLETE':return True
        for stage,(_,phase,raw) in zip(published,keep):
            if cancelled.is_set():raise KeepReview()
            plan=json.loads(stage[2]);proof=json.loads(stage[3])
            data=json.loads(raw)
            selection=KeepSelection(**data['selection'])
            options=Options(**data['options'])
            client=self.client_factory(options,self.secrets.sonarr_api_key())
            series=client.series(selection.tvdb_series_id)
            if not series or (series.get('id'),series.get('path'))!=(
                    data['series_id'],data['series_path']):
                raise KeepReview()
            episode=client.episode(selection,series)
            if episode.get('id')!=data['episode_id'] or not episode.get('hasFile'):
                raise KeepReview()
            record=client.request(
                'episodefile/'+str(data['result']['episode_file_id']))
            def guard():
                if cancelled.is_set():raise KeepReview()
                with self.queue.connection() as db,transaction(db):
                    self.facts(db,claim,decision)
                current=client.request(
                    'episodefile/'+str(data['result']['episode_file_id']))
                if existing_file(
                        options,series,episode,current,
                        data['source_file'][2])!=data['result']:
                    raise KeepReview()
            guard()
            self.remove(stage[2],stage[3],guard,options.keep_root)
        with self.queue.connection() as db,transaction(db):
            self.facts(db,claim,decision)
            changed=db.execute(
                "UPDATE batch_keep_cleanup SET phase='COMPLETE',updated_at_ms=? "
                "WHERE job_id=? AND decision_job_id=? AND phase='PENDING'",
                (self.queue.now(),claim.job_id,decision)).rowcount
            if changed!=1:raise KeepReview()
        return True
