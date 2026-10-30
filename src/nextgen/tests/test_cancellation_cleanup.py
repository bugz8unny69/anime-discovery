"""Offline real local files with fake client control only; unexecuted."""
from dataclasses import replace
from pathlib import Path
import unittest

from src.nextgen.acquisition.submission import ClientUnavailable
from src.nextgen.cancellation_service import CancellationService
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests import test_torrent_transfer as fixture
from src.nextgen.tests.test_torrent_submission import Secrets


class CancellationCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.TorrentTransferTests.asyncSetUp
    rows=fixture.TorrentTransferTests.rows
    source=fixture.TorrentTransferTests.source
    worker=fixture.TorrentTransferTests.worker
    queued=fixture.TorrentTransferTests.queued

    async def setup_download(self):
        worker=self.worker()
        self.store.update({'storage':{'download_root':str(self.root/'downloads')}},expected_revision=2)
        await self.queued(worker);await worker.attempt()
        self.job=self.rows("SELECT job_id FROM jobs WHERE kind='DOWNLOAD_TORRENT'")[0][0]
        self.payload_root=Path(self.snapshot.observation.save_path)
        self.payload_root.mkdir(parents=True)
        self.video=self.payload_root/self.snapshot.observation.files[0].path
        self.video.write_bytes(b'v'*100)
        self.stops=self.removals=0
        return worker

    def service(self,mode='normal'):
        test=self
        class FakeClient:
            major=5
            def __init__(self,*args):pass
            def login(self):pass
            def inspect(self,expected):return None if test.snapshot is None else test.snapshot.observation
            def cleanup_control(self,intent,fingerprint,permit,action):
                permit.take(fingerprint,action)
                if action=='stop':
                    test.stops+=1
                    if mode!='stop_timeout_absent':test.snapshot=replace(test.snapshot,observation=replace(test.snapshot.observation,state='stoppedDL'))
                    if mode.startswith('stop_timeout'):raise ClientUnavailable()
                else:
                    test.removals+=1
                    if mode!='remove_timeout_present':test.snapshot=None
                    if mode.startswith('remove_timeout'):raise ClientUnavailable()
        return CancellationService(self.store.read(),Secrets(),client_factory=FakeClient)

    async def test_cancel_active_download_removes_owned_torrent_then_exact_files(self):
        await self.setup_download()
        result=self.service().cancel(self.job)
        self.assertEqual(result['cleanup_state'],'COMPLETE')
        self.assertEqual((self.stops,self.removals),(1,1))
        self.assertFalse(self.video.exists())
        self.assertFalse(self.payload_root.exists())  # Empty ad-* folder removed; rmdir only.
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='DOWNLOAD_TORRENT'"),[('CANCELED',)])
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'COMPLETE')
        self.assertEqual((self.stops,self.removals),(1,1))

    async def test_lost_stop_response_reconciles_without_repeating_stop(self):
        await self.setup_download()
        self.assertEqual(self.service('stop_timeout_present').cancel(self.job)['cleanup_state'],'PENDING')
        self.assertTrue(self.video.exists())
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'COMPLETE')
        self.assertEqual((self.stops,self.removals),(1,1))

    async def test_uncertain_stop_that_stays_active_never_rearms(self):
        await self.setup_download()
        self.service('stop_timeout_absent').cancel(self.job)
        for _ in range(2):self.service().cleanup(self.job)
        self.assertEqual((self.stops,self.removals),(1,0))
        self.assertTrue(self.video.exists())

    async def test_lost_delete_response_reconciles_absence_and_resumes_files(self):
        await self.setup_download()
        result=self.service('remove_timeout_absent').cancel(self.job)
        self.assertEqual(result['cleanup_state'],'PENDING')
        self.assertTrue(self.video.exists())
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'COMPLETE')
        self.assertFalse(self.video.exists())
        self.assertEqual(self.removals,1)

    async def test_uncertain_delete_while_still_present_is_not_replayed(self):
        await self.setup_download()
        self.service('remove_timeout_present').cancel(self.job)
        for _ in range(2):self.service().cleanup(self.job)
        self.assertEqual(self.removals,1)
        self.assertTrue(self.video.exists())

    async def test_changed_file_after_torrent_removal_is_preserved_for_review(self):
        await self.setup_download()
        self.service('remove_timeout_absent').cancel(self.job)
        self.video.write_bytes(b'changed')
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual(self.video.read_bytes(),b'changed')

    async def test_unknown_files_symlinks_and_hardlinks_prevent_removal(self):
        import os
        await self.setup_download()
        other=self.payload_root/'unknown.txt';other.write_bytes(b'preserve')
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual(self.removals,0)
        other.unlink()
        self.video.unlink();self.video.symlink_to(self.root/'outside')
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual(self.removals,0)
        self.video.unlink();self.video.write_bytes(b'v'*100)
        os.link(self.video,self.root/'hardlink')
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual(self.removals,0)

    async def test_other_explicit_consumer_preserves_torrent_and_files(self):
        from src.nextgen.storage.sqlite import enqueue_job
        await self.setup_download()
        prep=self.rows("SELECT job_id FROM jobs WHERE kind='PREPARE_ACQUISITION'")[0][0]
        event=self.rows('SELECT event_id FROM jobs WHERE job_id=?',(prep,))[0][0]
        db=connect(self.database)
        try:
            with transaction(db):enqueue_job(db,kind='DOWNLOAD_TORRENT',payload={'preparation_job_id':prep},component='api',event_id=event)
        finally:db.close()
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual((self.stops,self.removals),(0,0))
        self.assertTrue(self.video.exists())

    async def test_changed_marker_is_never_stopped_or_removed(self):
        await self.setup_download()
        self.snapshot=replace(self.snapshot,observation=replace(self.snapshot.observation,tags=()))
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'REVIEW')
        self.assertEqual((self.stops,self.removals),(0,0))

    async def test_crash_after_delete_intent_cannot_regain_remove_permit(self):
        await self.setup_download()
        test=self
        class LosePermit(CancellationService):
            def _advance(self,intent,prior,phase,files=None):
                super()._advance(intent,prior,phase,files)
                if phase=='REMOVE_UNCERTAIN':raise ClientUnavailable()
        ordinary=self.service()
        service=LosePermit(self.store.read(),Secrets(),client_factory=ordinary.client_factory)
        service.cancel(self.job)
        for _ in range(2):ordinary.cleanup(self.job)
        self.assertEqual(self.removals,0)
        self.assertTrue(self.video.exists())

    async def test_download_done_but_not_staged_still_offers_cancel(self):
        worker=await self.setup_download()
        self.snapshot=replace(self.snapshot,progress=(1,))
        fixture.TorrentTransferTests.due(self)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='DOWNLOAD_TORRENT'"),[('DONE',)])
        self.assertTrue(self.service().status(self.job)['can_cancel'])
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'COMPLETE')
        self.assertFalse(self.video.exists())
        # Historical completed stages remain DONE; operation records cancellation.
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='DOWNLOAD_TORRENT'"),[('DONE',)])

    async def test_crash_after_stop_intent_does_not_regain_stop_permit(self):
        await self.setup_download()
        class LosePermit(CancellationService):
            def _advance(self,intent,prior,phase,files=None):
                super()._advance(intent,prior,phase,files)
                if phase=='STOP_UNCERTAIN':raise ClientUnavailable()
        ordinary=self.service()
        service=LosePermit(self.store.read(),Secrets(),client_factory=ordinary.client_factory)
        service.cancel(self.job)
        for _ in range(2):ordinary.cleanup(self.job)
        self.assertEqual((self.stops,self.removals),(0,0))
        self.assertTrue(self.video.exists())
