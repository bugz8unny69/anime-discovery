"""Offline v28 batch trial integration: no external acquisition."""
import tempfile
from pathlib import Path
import unittest

from dataclasses import replace
from src.nextgen.acquisition.metadata import BatchInventory, TorrentFile, AcquisitionConflict
from src.nextgen.storage.batch_acquisition_candidate import load_batch_acquisition_candidate
from src.nextgen.batch.provider_worker import BatchVerificationCompletion
from src.nextgen.batch.verification import verify_batch_files
from src.nextgen.configuration import ConfigurationStore
from src.nextgen.job_contracts import Registry, Policy
from src.nextgen.jobs.verify_release_job import registration as release_registration
from src.nextgen.jobs.evaluate_batch_job import registration as batch_registration
from src.nextgen.jobs.reserve_batch_job import registration as reserve_batch_registration
from src.nextgen.providers.http import Credentials
from src.nextgen.storage.sqlite import connect, initialize, accept_event_and_job, save_identity
from src.nextgen.worker import Worker


class FakeProvider:
    def episodes(self,aid):return {i:1000+i for i in range(1,13)}
    def mapping_xml(self):
        return b'<anime-list><anime anidbid="123" tvdbid="456" defaulttvdbseason="1"/></anime-list>'
    def episode_page(self,tid,page,secret):
        return tuple((2000+i,1,i) for i in range(1,13)),False


class BatchTrialWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        self.database=root/'db.sqlite'
        self.store=ConfigurationStore(root)
        self.startup=self.store.initialize({'storage':{'database_path':str(self.database)}}).snapshot
        db=connect(self.database)
        initialize(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(),(29,))
        self.event,self.verification_job=accept_event_and_job(
            db,'test',b'{"release_name":"Shiki (S01 + OVA)","torrent_infohash":"'+b'a'*40+b'"}',
            kind='VERIFY_RELEASE',payload={'anidb_id':123})
        save_identity(db,self.event,{'schema_version':2,'anime':{
            'anidb_id':123,'tvdb_series_id':456,'title':'Shiki'}})
        db.close()
        files=tuple(TorrentFile(i,f'Shiki/Season 01/Shiki S01E{i+1:02d}.mkv',
                                100000000) for i in range(12))
        self.inventory=BatchInventory('a'*40,'b'*64,files+(
            TorrentFile(12,'Shiki/OVA/Shiki OVA 01.mkv',100000000),))
        self.verified=verify_batch_files(
            self.inventory,client=FakeProvider(),credentials=Credentials('secret'),
            anidb_id=123,tvdb_series_id=456,season=1)

    def rows(self,sql):
        db=connect(self.database)
        try:return db.execute(sql).fetchall()
        finally:db.close()

    def worker(self, *, reserve=False):
        async def verify(source,*args):
            return BatchVerificationCompletion(source,self.inventory,self.verified)
        worker=Worker(self.store,self.startup,Registry((
            release_registration(verify,batch_kind='EVALUATE_BATCH'),
            batch_registration(reservation_kind='RESERVE_BATCH' if reserve else None),
            *( (reserve_batch_registration(),) if reserve else () ))),policy=Policy(lease_ms=30000))
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_batch_trial_is_immutable_and_does_not_acquire(self):
        worker=self.worker()
        await worker.attempt()
        await worker.attempt()
        self.assertEqual(self.rows('SELECT kind,state FROM jobs ORDER BY job_id'),[
            ('VERIFY_RELEASE','DONE'),('EVALUATE_BATCH','DONE')])
        self.assertEqual(self.rows('SELECT anchor_episode,backfill_count,'
                                   'following_count,planned_size_bytes FROM batch_trial_plans'),
                         [(1,6,1,600000000)])
        self.assertEqual(self.rows('SELECT tvdb_episode,file_index FROM batch_trial_files '
                                   'ORDER BY tvdb_episode'),
                         [(i,i-1) for i in range(1,7)])
        for table in ('episode_reservations','acquisition_plans','torrent_submissions',
                      'torrent_transfers','staging_publications'):
            self.assertEqual(self.rows('SELECT count(*) FROM '+table),[(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM batch_verified_files'),[(12,)])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'),[])

    async def test_opt_in_reserves_regular_episodes_atomically_without_torrent(self):
        worker=self.worker(reserve=True)
        for _ in range(3):
            await worker.attempt()
        self.assertEqual(self.rows('SELECT kind,state FROM jobs ORDER BY job_id'),[
            ('VERIFY_RELEASE','DONE'),('EVALUATE_BATCH','DONE'),
            ('RESERVE_BATCH','DONE')])
        self.assertEqual(self.rows('SELECT tvdb_episode,file_index FROM '
                                   'batch_episode_reservations ORDER BY tvdb_episode'),
                         [(i,i-1) for i in range(1,7)])
        self.assertEqual(self.rows("SELECT state FROM batch_episode_reservations"),[
            ('ACTIVE',)]*6)
        for table in ('episode_reservations','acquisition_plans','torrent_submissions',
                      'torrent_transfers','staging_publications'):
            self.assertEqual(self.rows('SELECT count(*) FROM '+table),[(0,)])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'),[])
        reserve_job=self.rows("SELECT job_id FROM jobs WHERE kind='RESERVE_BATCH'")[0][0]
        candidate=load_batch_acquisition_candidate(self.database,reserve_job,self.inventory)
        self.assertEqual(candidate.probe_index,0)
        self.assertEqual(candidate.planned_episodes,tuple((i,i-1) for i in range(1,7)))
        self.assertEqual(candidate.skipped_indices,tuple(range(6,13)))
        with self.assertRaises(AcquisitionConflict):
            load_batch_acquisition_candidate(self.database,reserve_job,
                replace(self.inventory,info_sha256='c'*64))

    async def test_two_competing_packs_cannot_claim_same_episodes(self):
        db=connect(self.database)
        try:
            event,job=accept_event_and_job(
                db,'second-delivery',
                b'{"release_name":"Shiki S01 + OVA","torrent_infohash":"'+b'a'*40+b'"}',
                kind='VERIFY_RELEASE',payload={'anidb_id':123})
            save_identity(db,event,{'schema_version':2,'anime':{
                'anidb_id':123,'tvdb_series_id':456,'title':'Shiki'}})
        finally:db.close()
        worker=self.worker(reserve=True)
        for _ in range(6):
            await worker.attempt()
        self.assertEqual(self.rows(
            "SELECT state FROM jobs WHERE kind='RESERVE_BATCH' ORDER BY job_id"),
            [('DONE',),('ON_HOLD',)])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM batch_episode_reservations WHERE state='ACTIVE'"),[(6,)])
        self.assertEqual(self.rows(
            "SELECT distinct owner_job_id FROM batch_episode_reservations"),[
                (self.rows("SELECT job_id FROM jobs WHERE kind='RESERVE_BATCH' "
                           "ORDER BY job_id LIMIT 1")[0][0],)])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'),[])

    async def test_missing_episode_one_requires_review_without_reservation(self):
        # An otherwise provider-confirmed pack cannot guess the trial anchor.
        # Reindex a pack whose first regular episode is E02.
        self.inventory=BatchInventory('a'*40,'b'*64,tuple(
            TorrentFile(i,raw.path,raw.size) for i,raw in enumerate(self.inventory.files[1:])))
        self.verified=verify_batch_files(
            self.inventory,client=FakeProvider(),credentials=Credentials('secret'),
            anidb_id=123,tvdb_series_id=456,season=1)
        worker=self.worker()
        await worker.attempt()
        await worker.attempt()
        self.assertEqual(self.rows('SELECT kind,state,last_reason_code FROM jobs ORDER BY job_id'),[
            ('VERIFY_RELEASE','DONE',None),
            ('EVALUATE_BATCH','NEEDS_REVIEW','TRIAL_PLAN_CONFLICT')])
        self.assertEqual(self.rows('SELECT count(*) FROM batch_trial_plans'),[(0,)])
