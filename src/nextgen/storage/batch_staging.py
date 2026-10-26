"""Fenced copy-only stage plans and artifact receipts for a verified season.

Use the existing Publisher and staging_cleanup_artifacts machinery. Each
episode has its own durable immutable manifest, no overwrite and no source
deletion. All published episodes are committed together at worker completion.
"""
import json
from pathlib import PurePosixPath
from types import SimpleNamespace

from src.nextgen.staging import StagingReview, specification, encoded, disjoint, root_identity
from src.nextgen.storage.staging import Journal as SingleJournal
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.sqlite import transaction


def _facts(db,claim,media_job):
    if claim.kind!='STAGE_BATCH_FILES':raise StagingReview()
    row=db.execute(
        "SELECT v.job_id,v.event_id,v.state,u.plan_id,s.reservation_job_id,"
        "s.save_path,s.fingerprint,s.state,o.state "
        "FROM jobs stage JOIN jobs v ON v.job_id=stage.created_by_job_id "
        "JOIN batch_torrent_unlocks u ON u.unlock_job_id=v.created_by_job_id "
        "JOIN batch_torrent_submissions s ON s.plan_id=u.plan_id "
        "JOIN job_operation_members sm ON sm.job_id=stage.job_id "
        "JOIN job_operation_members vm ON vm.job_id=v.job_id "
        "AND vm.operation_id=sm.operation_id "
        "JOIN job_operations o ON o.operation_id=vm.operation_id "
        "WHERE stage.job_id=? AND v.job_id=? AND v.kind='VERIFY_BATCH_FILES'",
        (claim.job_id,media_job)).fetchone()
    if (row is None or row[:3]!=(media_job,claim.event_id,'DONE')
            or row[7]!='OWNED_STOPPED' or row[8]!='ACTIVE'):
        raise StagingReview()
    plan_id=row[3]
    records=db.execute(
        "SELECT t.file_index,t.tvdb_episode,p.evidence_json,"
        "f.anidb_episode_id,f.tvdb_episode_id,b.anidb_id,"
        "b.tvdb_series_id,b.tvdb_season,a.title "
        "FROM batch_trial_files t "
        "JOIN batch_verified_media_files p ON p.plan_id=t.plan_id "
        "AND p.file_index=t.file_index AND p.tvdb_episode=t.tvdb_episode "
        "JOIN batch_trial_plans tp ON tp.plan_id=t.plan_id "
        "JOIN batch_verifications b ON b.batch_id=tp.batch_id "
        "JOIN batch_verified_files f ON f.batch_id=b.batch_id "
        "AND f.file_index=t.file_index AND f.tvdb_episode=t.tvdb_episode "
        "JOIN identified_anime a ON a.anidb_id=b.anidb_id "
        "WHERE t.plan_id=? ORDER BY t.tvdb_episode",
        (plan_id,)).fetchall()
    expected=db.execute(
        "SELECT count(*) FROM batch_trial_files WHERE plan_id=?",
        (plan_id,)).fetchone()[0]
    if not records or len(records)!=expected:raise StagingReview()
    result=[]
    for index,ep,raw,anidb_episode,tvdb_episode,aid,tid,season,title in records:
        try:
            evidence=json.loads(raw)
            if (type(evidence) is not dict
                    or set(evidence)!={'path','root','file','sha256','duration_ms','languages'}
                    or evidence['languages']!=['eng','jpn']
                    or len(evidence['file'])!=5):
                raise StagingReview()
        except (TypeError,ValueError,KeyError):
            raise StagingReview() from None
        identity=(aid,anidb_episode,tid,season,ep,tvdb_episode,title)
        result.append((index,ep,evidence,identity))
    return plan_id,row[5],tuple(result)


class BatchStagingJournal(SingleJournal):
    def prepare_episode(self,claim,media_job,position,configuration):
        with self.queue.connection() as db,transaction(db):
            self.queue._owns(db,claim,self.queue.now())
            plan_id,source_root,entries=_facts(db,claim,media_job)
            if type(position) is not int or not 0<=position<len(entries):
                raise StagingReview()
            index,episode,evidence,identity=entries[position]
            prior=db.execute(
                "SELECT job_id,manifest_json FROM batch_staging_publications "
                "WHERE plan_id=? AND file_index=?",
                (plan_id,index)).fetchone()
            if prior is not None:
                if prior[0]!=claim.job_id:raise StagingReview()
                plan=json.loads(prior[1])
                if (plan['source']!=evidence or plan['source_root']!=source_root
                        or plan.get('transfer')!='COPY'):
                    raise StagingReview()
                return index,episode,plan
            root=configuration.value('storage.trial_root')
            disjoint(root,(source_root,configuration.value('storage.download_root'),
                           configuration.value('storage.keep_root'),
                           configuration.value('storage.database_path')))
            intent=SimpleNamespace(options=SimpleNamespace(download_root=source_root))
            plan=specification(intent,evidence,identity,root,configuration.desired_revision)
            plan['transfer']='COPY'
            plan['root_identity']=root_identity(root)
            raw=encoded(plan)
            if len(raw.encode('utf-8'))>65536:raise StagingReview()
            db.execute(
                "INSERT INTO batch_staging_publications "
                "(plan_id,file_index,tvdb_episode,job_id,manifest_json,state,created_at_ms) "
                "VALUES(?,?,?,?,?,'PLANNED',?)",
                (plan_id,index,episode,claim.job_id,raw,self.queue.now()))
            self.queue._owns(db,claim,self.queue.now())
            return index,episode,plan

    def count(self,claim,media_job):
        with self.queue.connection() as db,transaction(db):
            self.queue._owns(db,claim,self.queue.now())
            _,_,records=_facts(db,claim,media_job)
            return len(records)


def persist_batch_staging(db,claim,media_job,receipts):
    """Validate every episode's published inode receipts, then mark STAGED."""
    from src.nextgen.staging import StagingReview
    from src.nextgen.storage.cancellation import operation
    from time import time_ns
    if not db.in_transaction or claim.kind!='STAGE_BATCH_FILES':
        raise StagingReview()
    plan_id,source_root,entries=_facts(db,claim,media_job)
    if (type(receipts) is not tuple or len(receipts)!=len(entries)
            or len({x[0] for x in receipts})!=len(entries)):
        raise StagingReview()
    op=operation(db,claim.job_id)
    if op[1]!='ACTIVE':raise StagingReview()
    now=time_ns()//1000000
    for (index,episode,evidence,identity),(seen_index,saved) in zip(entries,receipts):
        if seen_index!=index or type(saved) is not list or len(saved)!=3:
            raise StagingReview()
        row=db.execute(
            "SELECT job_id,manifest_json,state FROM batch_staging_publications "
            "WHERE plan_id=? AND file_index=?",
            (plan_id,index)).fetchone()
        if row is None or row[0]!=claim.job_id or row[2]!='PLANNED':
            raise StagingReview()
        plan=json.loads(row[1])
        if plan['source']!=evidence or plan['source_root']!=source_root or plan['transfer']!='COPY':
            raise StagingReview()
        for entry,receipt in zip(plan['entries'],saved):
            if (type(receipt) is not dict or
                    set(receipt)!={'role','path','root','file','sha256','hash_checked','artifact'}
                    or receipt['role']!=entry['role'] or receipt['path']!=entry['path']
                    or receipt['sha256']!=entry['sha256']
                    or receipt['hash_checked'] is not (entry['role']!='media')
                    or type(receipt['file']) is not list
                    or len(receipt['file'])!=5 or receipt['file'][2]!=entry['size']):
                raise StagingReview()
            if receipt['artifact'] is None:
                if entry['role']!='series':raise StagingReview()
            else:
                artifact=db.execute(
                    "SELECT job_id,operation_id,root_path,relative_path,"
                    "root_device,root_inode,file_device,file_inode,phase "
                    "FROM staging_cleanup_artifacts WHERE artifact_id=?",
                    (receipt['artifact'],)).fetchone()
                expected=(claim.job_id,op[0],
                          plan['root']+'/'+str(PurePosixPath(entry['path']).parent),
                          entry['temporary'],*receipt['root'],*receipt['file'][:2],'PUBLISHED')
                if artifact!=expected:raise StagingReview()
        db.execute(
            "UPDATE batch_staging_publications SET state='PUBLISHED',"
            "receipts_json=?,published_at_ms=? WHERE plan_id=? AND file_index=?",
            (encoded(saved),now,plan_id,index))
    # A staged pack is complete only once every selected episode is published.
    published=db.execute(
        "SELECT count(*) FROM batch_staging_publications "
        "WHERE plan_id=? AND state='PUBLISHED'",(plan_id,)).fetchone()[0]
    if published!=len(entries):raise StagingReview()
    db.execute(
        "UPDATE job_operations SET state='STAGED',updated_at_ms=? "
        "WHERE operation_id=? AND state='ACTIVE'",
        (now,op[0]))
    return ()
