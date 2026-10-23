"""Offline declared-release/provider/worker integration; authored, not executed."""
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest

from src.nextgen.configuration import ConfigurationStore
from src.nextgen.configuration_schema import ConfigurationSnapshot
from src.nextgen.job_contracts import Outcome, Registry, Policy
from src.nextgen.jobs.verify_release_job import registration
from src.nextgen.providers.errors import ProviderInvalidResponse
from src.nextgen.providers.http import Options, Credentials
from src.nextgen.providers.release_mapping import declared_episode, forward_mappings
from src.nextgen.providers.releases import make_verifier
from src.nextgen.release_contracts import VerifiedRelease, ReleaseInput, ReleaseNotReady, ReleaseConflict
from src.nextgen.storage.job_queue import LeaseLost
from src.nextgen.storage.releases import load_release
from src.nextgen.storage.sqlite import connect, initialize, save_identity, accept_event_and_job
from src.nextgen.worker import Worker

MAPPING=b'<anime-list><anime anidbid="123" tvdbid="456" defaulttvdbseason="2" episodeoffset="12"/></anime-list>'


class ReleaseMappingTests(unittest.TestCase):
    def test_single_declarations_do_not_apply_legacy_trial_window_or_season_one_rule(self):
        self.assertEqual(declared_episode('[Group] Test - 12 [1080p]'),('anidb',None,12))
        self.assertEqual(declared_episode('Test S02E13'),('tvdb',2,13))
        self.assertEqual(declared_episode('Test S00E01'),('tvdb',0,1))
        for title in ('Test Batch E01','Test E01-E02','Test E01E02','Test S01E01E02',
                      'Test - 01 & 02','Test EP01EP02','Test EP01.5','Test E01.5','Test E00','Test S02','Test Movie - 01','Test E01 E02','Test EP01a','Test S01E01a','Test - -01'):
            with self.subTest(title=title),self.assertRaises(ReleaseNotReady): declared_episode(title)

    def test_explicit_offset_remap_and_season_zero_supported_without_guessing(self):
        self.assertEqual(forward_mappings(MAPPING,123,456,{1:987,2:988}),{1:(2,13),2:(2,14)})
        custom=MAPPING.replace(b'/></anime-list>',b'><mapping-list><mapping anidbseason="1" tvdbseason="0">1-5;</mapping></mapping-list></anime></anime-list>')
        self.assertEqual(forward_mappings(custom,123,456,{1:987})[1],(0,5))
        missing=MAPPING.replace(b' episodeoffset="12"',b'')
        self.assertEqual(forward_mappings(missing,123,456,{1:987}),{})
        with self.assertRaises(ReleaseConflict): forward_mappings(MAPPING,123,999,{1:987})
        split=custom.replace(b'1-5;',b'1-5+6;')
        with self.assertRaises(ReleaseNotReady): forward_mappings(split,123,456,{1:987})


class ReleaseVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source=ReleaseInput(1,1,123,456,b'{"release_name":"Test S02E13"}')
        self.cancelled=threading.Event()
        self.configuration=ConfigurationSnapshot(1,{})
        owner=self
        class Client:
            def episodes(self,aid): return {1:987,2:988}
            def mapping_xml(self): return MAPPING
            def episode_page(self,tid,page,credentials):
                owner.pages.append(page)
                return ((100,2,13),),False
        self.client=Client()
        self.pages=[]
        self.verify=make_verifier(Options('registeredclient',1),lambda:Credentials('private-key'),
                                  client_factory=lambda *args:self.client)

    async def test_reverse_offset_uses_exact_anidb_id_and_tvdb_record(self):
        value=await self.verify(self.source,self.configuration,self.cancelled)
        self.assertEqual((value.anidb_episode_number,value.anidb_episode_id,value.tvdb_season,
                          value.tvdb_episode,value.tvdb_episode_id),(1,987,2,13,100))
        self.assertEqual(self.pages,[0])

    async def test_all_pages_must_finish_and_duplicates_or_merged_evidence_are_rejected(self):
        def pages(tid,page,credentials):
            self.pages.append(page)
            return (((100,2,13),),True) if page==0 else (((101,2,14),),False)
        self.client.episode_page=pages
        value=await self.verify(self.source,self.configuration,self.cancelled)
        self.assertEqual(value.tvdb_episode_id,100)
        self.assertEqual(self.pages,[0,1])
        self.client.episode_page=lambda *args:(((100,2,13),),True)
        with self.assertRaises(ProviderInvalidResponse): await self.verify(self.source,self.configuration,self.cancelled)
        self.client.episode_page=lambda *args:(((100,2,13),(101,2,13)),False)
        with self.assertRaises(ReleaseConflict): await self.verify(self.source,self.configuration,self.cancelled)

    async def test_pack_missing_mapping_and_cancellation_are_reviewable(self):
        for raw in (b'{"release_name":"Test Batch"}',b'{"release_name":"Test - 99"}'):
            with self.assertRaises(ReleaseNotReady):
                await self.verify(replace(self.source,raw_body=raw),self.configuration,self.cancelled)
        self.cancelled.set()
        with self.assertRaises(ReleaseNotReady): await self.verify(self.source,self.configuration,self.cancelled)


class ReleaseJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.database=self.root/'queue.sqlite'
        self.store=ConfigurationStore(self.root)
        self.startup=self.store.initialize({'storage':{'database_path':str(self.database)}}).snapshot
        db=connect(self.database)
        initialize(db)
        self.event,self.job=accept_event_and_job(db,'test',b'{"release_name":"Test - 01"}',
                                                kind='VERIFY_RELEASE',payload={'anidb_id':123})
        save_identity(db,self.event,{'schema_version':2,'anime':{'anidb_id':123,'tvdb_series_id':456,'title':'Test'}})
        db.close()

    def rows(self,sql,args=()):
        db=connect(self.database)
        try:return db.execute(sql,args).fetchall()
        finally:db.close()

    def worker(self,verify):
        worker=Worker(self.store,self.startup,Registry((registration(verify),)),policy=Policy(lease_ms=30000))
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_worker_persists_declared_scope_without_mutating_identity_or_starting_acquisition(self):
        before=self.rows('SELECT series_json FROM identity_results')
        async def verify(source,*args):return VerifiedRelease(source,1,987,2,13,100)
        worker=self.worker(verify)
        await worker.attempt()
        self.assertEqual(self.rows('SELECT verification_scope,anidb_episode_id,tvdb_season,tvdb_episode,tvdb_order FROM release_verifications'),
                         [('DECLARED_SINGLE_EPISODE',987,2,13,'official')])
        self.assertEqual(self.rows('SELECT series_json FROM identity_results'),before)
        self.assertEqual(self.rows('SELECT kind,state FROM jobs'),[('VERIFY_RELEASE','DONE')])
        self.assertEqual(self.rows('SELECT * FROM identified_episodes'),[(987,123)])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'),[])

    async def test_source_change_during_provider_work_rolls_back_facts_and_reviews_job(self):
        async def verify(source,*args):
            db=connect(self.database)
            try:
                with db:db.execute('UPDATE incoming_events SET raw_body=? WHERE event_id=?',(b'changed',self.event))
            finally:db.close()
            return VerifiedRelease(source,1,987,2,13,100)
        await self.worker(verify).attempt()
        self.assertEqual(self.rows('SELECT count(*) FROM release_verifications'),[(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM identified_episodes'),[(0,)])
        self.assertEqual(self.rows('SELECT state,last_reason_code FROM jobs'),[('NEEDS_REVIEW','RELEASE_CONFLICT')])

    async def test_stale_lease_cannot_commit_release_facts(self):
        async def verify(source,*args): return VerifiedRelease(source,1,987,2,13,100)
        worker=self.worker(verify)
        worker.queue.clock=lambda:1000
        claim,_=worker.queue.claim()
        spec=worker.registry.entries['VERIFY_RELEASE']
        worker.queue.start(claim,spec,'a'*32,worker.registry)
        source=load_release(self.database,self.event,123)
        worker.queue.clock=lambda:31000
        with self.assertRaises(LeaseLost):
            worker.queue.finish(claim,Outcome(value=VerifiedRelease(source,1,987,2,13,100)),
                                spec=spec,invocation='a'*32,registry=worker.registry)
        self.assertEqual(self.rows('SELECT count(*) FROM release_verifications'),[(0,)])

    async def test_ambiguous_release_goes_to_review(self):
        async def verify(*args):raise ReleaseNotReady()
        await self.worker(verify).attempt()
        self.assertEqual(self.rows('SELECT state,last_reason_code FROM jobs'),[('NEEDS_REVIEW','RELEASE_UNRESOLVED')])


    async def test_provider_wait_defers_without_persisting_release_or_spending_retry_budget(self):
        from src.nextgen.providers.errors import ProviderDeferred
        async def verify(*args): raise ProviderDeferred(2000)
        await self.worker(verify).attempt()
        self.assertEqual(self.rows('SELECT state,last_reason_code FROM jobs'),[('RETRY_WAIT','JOB_WAITING')])
        self.assertEqual(self.rows("SELECT count(*) FROM job_history WHERE event_code='RETRY_SCHEDULED'"),[(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM release_verifications'),[(0,)])
