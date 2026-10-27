"""Real-file partial-batch cancellation checks without qBittorrent or CI.

The cancellation journal already stores exact staged inode proofs. Tests use
the production remover and the existing artifact phases, not invented paths.
"""
from contextlib import nullcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from src.nextgen.acquisition.media import signature
from src.nextgen.cancellation import CancellationError
from src.nextgen.staging_artifacts import (
    batch_copies, batch_copies_cleared, clean_published_batch,
)
from src.nextgen.storage.review_decisions import remove_selected


class PartialBatchStageCleanupTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home=Path(tmp.name)
        self.staging=home/'trial'
        self.staging.mkdir()
        self.keep=home/'keep'
        self.keep.mkdir()
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE batch_staging_publications(
                plan_id INTEGER,file_index INTEGER,job_id INTEGER,
                manifest_json TEXT,receipts_json TEXT,state TEXT);
            CREATE TABLE job_operation_members(
                job_id INTEGER,operation_id INTEGER);
            CREATE TABLE staging_cleanup_artifacts(
                artifact_id INTEGER,operation_id INTEGER,job_id INTEGER,
                root_path TEXT,relative_path TEXT,root_device INTEGER,
                root_inode INTEGER,file_device INTEGER,file_inode INTEGER,
                phase TEXT);
        """)
        self.queue=SimpleNamespace(connection=lambda:nullcontext(self.db))
        self.guards=0
        def guard(db=None):
            self.guards+=1
        self.guard=guard

    def publish(self,episode=1,*,plan_id=10):
        job=100+episode
        entries=[]
        receipts=[]
        for index,(role,relative,payload) in enumerate((
                ('media',f'Show/Season 01/E{episode:02d}.mkv',b'video'),
                ('episode',f'Show/Season 01/E{episode:02d}.nfo',b'episode'),
                ('series','Show/tvshow.nfo',b'series'))):
            path=self.staging/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_bytes(payload)
            info=path.stat()
            folder=path.parent.stat()
            artifact=(job*10+index if role!='series' else None)
            entries.append({
                'role':role,'path':relative,
                'temporary':'.ad-'+format(job*100+index,'032x')+'.partial',
            })
            receipts.append({
                'role':role,'path':relative,
                'root':[folder.st_dev,folder.st_ino],
                'file':list(signature(info)),
                'hash_checked':True,'artifact':artifact,
            })
            if artifact is not None:
                self.db.execute(
                    "INSERT INTO staging_cleanup_artifacts VALUES("
                    "?,?,?,?,?,?,?,?,?,?)",
                    (artifact,7,job,str(path.parent),
                     entries[-1]['temporary'],folder.st_dev,folder.st_ino,
                     info.st_dev,info.st_ino,'PUBLISHED'))
        root=self.staging.stat()
        manifest=json.dumps({
            'transfer':'COPY','root':str(self.staging),
            'root_identity':[root.st_dev,root.st_ino],
            'entries':entries,
        })
        proofs=json.dumps(receipts)
        self.db.execute('INSERT INTO batch_staging_publications VALUES(?,?,?,?,?,?)',
                        (plan_id,episode,job,manifest,proofs,'PUBLISHED'))
        self.db.execute('INSERT INTO job_operation_members VALUES(?,7)',(job,))
        self.db.commit()
        return self.staging/entries[0]['path'],self.staging/entries[1]['path']

    def cleanup(self,*,remove=None):
        kwargs={} if remove is None else {'remove':remove}
        return clean_published_batch(
            self.queue,7,guard=self.guard,keep_root=str(self.keep),**kwargs)

    def test_two_published_episodes_are_removed_but_shared_metadata_survives(self):
        first=self.publish(1)
        second=self.publish(2)
        extra=self.staging/'Show'/'unrelated.mkv'
        extra.write_bytes(b'do not delete')
        self.cleanup()
        for path in (*first,*second):
            self.assertFalse(path.exists())
        self.assertTrue((self.staging/'Show'/'tvshow.nfo').exists())
        self.assertTrue(extra.exists())
        self.assertTrue(batch_copies_cleared(self.db,7))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM staging_cleanup_artifacts "
            "WHERE phase='REMOVED'").fetchone(),(4,))
        self.cleanup()  # An already finished deletion may be retried.
        self.assertTrue(extra.exists())

    def test_changed_video_is_never_unlinked_or_marked_complete(self):
        from src.nextgen.staging_artifacts import BatchStageCleanupRetry
        video,_=self.publish(1)
        video.write_bytes(b'tampered video')
        with self.assertRaises(BatchStageCleanupRetry):
            self.cleanup()
        self.assertTrue(video.exists())
        self.assertFalse(batch_copies_cleared(self.db,7))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM staging_cleanup_artifacts "
            "WHERE phase='REMOVED'").fetchone(),(0,))

    def test_crash_after_unlink_before_receipt_is_safe_to_resume(self):
        video,episode=self.publish(1)
        calls=[]
        def interrupted(manifest,receipts,guard,keep_root):
            remove_selected(manifest,receipts,guard,keep_root)
            calls.append(True)
            raise OSError('lost write acknowledgement after unlink')
        with self.assertRaises(OSError):
            self.cleanup(remove=interrupted)
        self.assertFalse(video.exists())
        self.assertFalse(episode.exists())
        self.assertFalse(batch_copies_cleared(self.db,7))
        self.cleanup()
        self.assertTrue(batch_copies_cleared(self.db,7))
        self.assertEqual(calls,[True])

    def test_uncommitted_or_orphan_published_inode_is_preserved(self):
        from src.nextgen.staging_artifacts import BatchStageCleanupRetry
        video,episode=self.publish(1)
        self.db.execute(
            "UPDATE batch_staging_publications SET state='PLANNED',"
            "receipts_json=NULL")
        self.db.commit()
        with self.assertRaises(BatchStageCleanupRetry):
            self.cleanup()
        self.assertTrue(video.exists())
        self.assertTrue(episode.exists())

    def test_broken_receipt_or_foreign_artifact_blocks_deletion(self):
        video,_=self.publish(1)
        raw=self.db.execute(
            'SELECT receipts_json FROM batch_staging_publications'
        ).fetchone()[0]
        proofs=json.loads(raw)
        proofs[0]['artifact']=999999
        self.db.execute(
            'UPDATE batch_staging_publications SET receipts_json=?',
            (json.dumps(proofs),))
        self.db.commit()
        with self.assertRaises(CancellationError):
            self.cleanup()
        self.assertTrue(video.exists())

    def test_pinned_origin_is_protected_even_if_trial_root_setting_changes(self):
        from unittest.mock import patch
        from src.nextgen.batch_cancellation_cleanup import BatchCanceledCleanup
        from src.nextgen.acquisition.owned_cleanup import OwnedCleanup
        self.publish(1,plan_id=10)
        service=SimpleNamespace(
            queue=self.queue,configuration=object(),secrets=object(),
            client_factory=object(),files_factory=lambda intent,roots:tuple(roots),
            component='worker',_fence=lambda db=None:None,_log=lambda records:None,
            guard=None)
        cleaner=BatchCanceledCleanup(service)
        captured=[]
        def fake(parent,operation,intent):
            captured.extend(parent.files_factory(
                intent,('/different/new-trial','/different/keep')))
            return True
        with patch.object(OwnedCleanup,'_clean_target',fake):
            done=cleaner._clean_target(
                7,SimpleNamespace(plan=SimpleNamespace(plan_id=10)))
        self.assertTrue(done)
        self.assertIn(str(self.staging),captured)
        self.assertIn('/different/new-trial',captured)
        self.assertEqual(cleaner.files_factory,service.files_factory)

    def test_uncertain_rename_is_retried_without_deleting_unproven_media(self):
        from src.nextgen.staging_artifacts import BatchStageCleanupRetry
        video,_=self.publish(1)
        self.db.execute(
            "UPDATE batch_staging_publications SET state='PLANNED',"
            "receipts_json=NULL")
        self.db.execute(
            "UPDATE staging_cleanup_artifacts SET phase='PUBLISH_UNCERTAIN' "
            "WHERE artifact_id=(SELECT min(artifact_id) "
            "FROM staging_cleanup_artifacts)")
        self.db.commit()
        with self.assertRaises(BatchStageCleanupRetry):
            self.cleanup()
        self.assertTrue(video.exists())

    def test_interrupted_atomic_rename_is_cleaned_using_pinned_inode(self):
        from src.nextgen.staging_artifacts import reconcile_planned_batch
        video,episode=self.publish(1)
        self.db.execute(
            "UPDATE batch_staging_publications SET state='PLANNED',"
            "receipts_json=NULL")
        self.db.execute(
            "UPDATE staging_cleanup_artifacts SET phase='PUBLISH_UNCERTAIN'")
        self.db.commit()
        reconcile_planned_batch(self.queue,7,guard=self.guard,
                                keep_root=str(self.keep))
        self.cleanup()
        self.assertFalse(video.exists())
        self.assertFalse(episode.exists())
        self.assertTrue((self.staging/'Show'/'tvshow.nfo').exists())
        self.assertTrue(batch_copies_cleared(self.db,7))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM staging_cleanup_artifacts "
            "WHERE phase='REMOVED'").fetchone(),(2,))

    def test_recovery_refuses_an_inode_replaced_between_rename_and_cancel(self):
        from src.nextgen.staging_artifacts import (
            reconcile_planned_batch,BatchStageCleanupRetry,
        )
        video,_=self.publish(1)
        self.db.execute(
            "UPDATE batch_staging_publications SET state='PLANNED',"
            "receipts_json=NULL")
        self.db.execute(
            "UPDATE staging_cleanup_artifacts SET phase='PUBLISH_UNCERTAIN'")
        self.db.commit()
        video.unlink()
        video.write_bytes(b'an unrelated replacement')
        with self.assertRaises(BatchStageCleanupRetry):
            reconcile_planned_batch(self.queue,7,guard=self.guard,
                                    keep_root=str(self.keep))
        self.assertEqual(video.read_bytes(),b'an unrelated replacement')

    def test_uncertain_temp_is_cleaned_without_recursive_deletion(self):
        from src.nextgen.staging_artifacts import reconcile_planned_batch
        video,episode=self.publish(1)
        self.db.execute(
            "UPDATE batch_staging_publications SET state='PLANNED',"
            "receipts_json=NULL")
        self.db.execute(
            "UPDATE staging_cleanup_artifacts SET phase='PUBLISH_UNCERTAIN'")
        self.db.commit()
        plan=json.loads(self.db.execute(
            "SELECT manifest_json FROM batch_staging_publications").fetchone()[0])
        temp=self.staging/'Show'/'Season 01'/plan['entries'][0]['temporary']
        video.rename(temp)
        reconcile_planned_batch(self.queue,7,guard=self.guard,
                                keep_root=str(self.keep))
        self.cleanup()
        self.assertFalse(temp.exists())
        self.assertFalse(episode.exists())
        self.assertTrue((self.staging/'Show'/'tvshow.nfo').exists())
