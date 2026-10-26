"""Per-episode Sonarr Keep journal, using the existing single-file import logic.

Each selected episode has its own independent PLANNED -> ADD_UNCERTAIN ->
SERIES_READY -> IMPORT_UNCERTAIN -> COMPLETE intent. Never replay a network
write after an uncertain response. The source stays staged until import proof.
"""
from dataclasses import asdict
import json

from src.nextgen.keep_selection import KeepSelection
from src.nextgen.sonarr import KeepReview, Options
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.review_decisions import require_allowed
from src.nextgen.storage.sqlite import transaction
from src.nextgen.staging import disjoint


def _rows(db,claim,target):
    op=operation(db,target)
    if op[1]!='STAGED':raise KeepReview()
    action=db.execute(
        "SELECT operation_id,target_job_id FROM management_actions "
        "WHERE job_id=? AND action='KEEP'",(claim.job_id,)).fetchone()
    if action!=(op[0],target):raise KeepReview()
    result=db.execute(
        "SELECT s.plan_id,s.file_index,s.tvdb_episode,s.manifest_json,"
        "s.receipts_json,f.anidb_episode_id,f.tvdb_episode_id,"
        "b.anidb_id,b.tvdb_series_id,b.tvdb_season "
        "FROM batch_staging_publications s "
        "JOIN batch_trial_plans p USING(plan_id) "
        "JOIN batch_verifications b ON b.batch_id=p.batch_id "
        "JOIN batch_verified_files f ON f.batch_id=b.batch_id "
        "AND f.file_index=s.file_index AND f.tvdb_episode=s.tvdb_episode "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "WHERE m.operation_id=? AND s.state='PUBLISHED' "
        "ORDER BY s.tvdb_episode,s.file_index",(op[0],)).fetchall()
    if not result or len(result)>1000:raise KeepReview()
    plan_ids={row[0] for row in result}
    if len(plan_ids)!=1:raise KeepReview()
    count=db.execute(
        "SELECT count(*) FROM batch_trial_files WHERE plan_id=?",
        (next(iter(plan_ids)),)).fetchone()[0]
    if count!=len(result):raise KeepReview()
    require_allowed(db,result[0][7])
    return result


class BatchKeepJournal:
    def __init__(self,database,*,file_index):
        self.queue=JobQueue(database)
        self.file_index=file_index

    def _guard(self,db,claim):
        self.queue._owns(db,claim,self.queue.now())
        if claim.kind!='KEEP_MEDIA':raise KeepReview()
        row=db.execute(
            "SELECT target_job_id FROM management_actions "
            "WHERE job_id=? AND action='KEEP'",(claim.job_id,)).fetchone()
        if row is None:raise KeepReview()
        rows=_rows(db,claim,row[0])
        matching=[r for r in rows if r[1]==self.file_index]
        if len(matching)!=1:raise KeepReview()
        return matching[0]

    def load(self,claim,target,configuration):
        with self.queue.connection() as db,transaction(db):
            row=self._guard(db,claim)
            action=db.execute(
                "SELECT target_job_id FROM management_actions WHERE job_id=?",
                (claim.job_id,)).fetchone()
            if action!=(target,):raise KeepReview()
            prior=db.execute(
                "SELECT phase,data_json FROM batch_keep_imports "
                "WHERE job_id=? AND file_index=?",
                (claim.job_id,self.file_index)).fetchone()
            if prior is not None:
                data=json.loads(prior[1])
                if prior[0]=='PLANNED':
                    selection=KeepSelection(**data['selection'])
                    options=Options.capture(configuration,selection)
                    disjoint(options.keep_root,(selection.staging_root,))
                    disjoint(options.library_root,(options.staging_root,))
                    data['options']=options.data()
                    db.execute(
                        "UPDATE batch_keep_imports SET data_json=?,updated_at_ms=? "
                        "WHERE job_id=? AND file_index=?",
                        (json.dumps(data,sort_keys=True),self.queue.now(),
                         claim.job_id,self.file_index))
                return prior[0],data
            (plan_id,index,episode,manifest,receipts,anidb_episode,tvdb_episode,
             anidb_id,series_id,season)=row
            plan=json.loads(manifest)
            proofs=json.loads(receipts)
            media=[e for e in plan['entries'] if e['role']=='media']
            actual=[p for p in proofs if p['role']=='media']
            if (len(media)!=1 or len(actual)!=1
                    or media[0]['path']!=actual[0]['path']
                    or plan.get('transfer')!='COPY'):
                raise KeepReview()
            selection=KeepSelection(
                anidb_id,anidb_episode,series_id,tvdb_episode,season,
                episode,plan_id,plan['root'],media[0]['path'])
            options=Options.capture(configuration,selection)
            disjoint(options.keep_root,(selection.staging_root,))
            disjoint(options.library_root,(options.staging_root,))
            data={'selection':asdict(selection),'options':options.data(),
                  'root_identity':plan['root_identity'],
                  'source_file':actual[0]['file'],
                  'source_parent':actual[0]['root']}
            raw=json.dumps(data,sort_keys=True,allow_nan=False)
            if len(raw.encode())>65536:raise KeepReview()
            db.execute(
                "INSERT INTO batch_keep_imports"
                "(job_id,plan_id,file_index,phase,data_json,updated_at_ms)"
                " VALUES(?,?,?,'PLANNED',?,?)",
                (claim.job_id,plan_id,index,raw,self.queue.now()))
            return 'PLANNED',data

    def change(self,claim,prior,phase,data):
        raw=json.dumps(data,sort_keys=True,allow_nan=False)
        if len(raw.encode())>65536:raise KeepReview()
        with self.queue.connection() as db,transaction(db):
            self._guard(db,claim)
            changed=db.execute(
                "UPDATE batch_keep_imports SET phase=?,data_json=?,updated_at_ms=? "
                "WHERE job_id=? AND file_index=? AND phase=?",
                (phase,raw,self.queue.now(),claim.job_id,self.file_index,prior))
            if changed.rowcount!=1:raise KeepReview()

    def fence(self,claim):
        with self.queue.connection() as db,transaction(db):
            self._guard(db,claim)


def batch_keep_file_indices(db,claim,target):
    return tuple(row[1] for row in _rows(db,claim,target))


def is_batch_staged(db,target):
    op=operation(db,target)
    return db.execute(
        "SELECT 1 FROM batch_staging_publications s "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "WHERE m.operation_id=? AND s.state='PUBLISHED' LIMIT 1",
        (op[0],)).fetchone() is not None
