"""Offline verification-to-staging handoff and protected completion; unrun."""
from functools import partial
from pathlib import Path
import unittest

from src.nextgen.acquisition.media import verify_file
from src.nextgen.jobs.verify_media_job import registration as verify_registration
from src.nextgen.jobs.stage_trial_media_job import registration as stage_registration
from src.nextgen.staging import Publisher
from src.nextgen.storage.cancellation import CancellationStore
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests.test_torrent_transfer import TorrentTransferTests
from src.nextgen.tests.test_verify_media_job import VerifyMediaJobTests
from src.nextgen.tests.test_acquisition_preparation import AcquisitionPreparationTests
from src.nextgen.tests.test_media_verification import probe_bytes


class StageMediaJobTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=AcquisitionPreparationTests.asyncSetUp
    rows=AcquisitionPreparationTests.rows
    source=AcquisitionPreparationTests.source
    queued=TorrentTransferTests.queued
    due=TorrentTransferTests.due
    ready=VerifyMediaJobTests.ready

    def worker(self,publisher=None,additional=(),refresh_kind=None):
        verification=verify_registration(verify=partial(verify_file,read_probe=lambda *_:probe_bytes()),staging_kind='STAGE_TRIAL_MEDIA')
        staging=stage_registration(publisher_factory=publisher or partial(Publisher,allow_root=True),refresh_kind=refresh_kind)
        return TorrentTransferTests.worker(self,verification=verification,additional=(staging,*additional))

    async def staged_ready(self,worker):
        event,preparation,path=await self.ready(worker)
        target=self.root/'staging';target.mkdir()
        self.store.update({'storage':{'trial_root':str(target)}},expected_revision=3)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'"),[('PENDING',)])
        return target,path

    async def test_verified_move_metadata_and_done_commit_with_staged_milestone(self):
        worker=self.worker();target,source=await self.staged_ready(worker)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'"),[('DONE',)])
        self.assertEqual(self.rows('SELECT state FROM staging_publications'),[('PUBLISHED',)])
        self.assertEqual(self.rows("SELECT count(*) FROM job_operations WHERE state='STAGED'"),[(1,)])
        self.assertEqual(len(list(target.rglob('*.mkv'))),1)
        self.assertEqual(len(list(target.rglob('*.nfo'))),2)
        self.assertFalse(source.exists())
        job=self.rows("SELECT job_id FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'")[0][0]
        self.assertFalse(CancellationStore(self.database).status(job)['can_cancel'])
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind='KEEP_MEDIA'"),[(0,)])

    async def test_metadata_failure_retains_video_and_does_not_mark_staged(self):
        class FailMetadata(Publisher):
            def _copy(self,plan,entry,fd):
                if entry['role']=='episode':raise OSError('metadata unavailable')
                return super()._copy(plan,entry,fd)
        worker=self.worker(partial(FailMetadata,allow_root=True));target,source=await self.staged_ready(worker)
        await worker.attempt()
        self.assertEqual(len(list(target.rglob('*.mkv'))),1)
        self.assertFalse(source.exists())
        self.assertEqual(self.rows("SELECT count(*) FROM job_operations WHERE state='STAGED'"),[(0,)])
        self.assertEqual(self.rows('SELECT state FROM staging_publications'),[('PLANNED',)])

    async def test_cancel_after_copy_fences_database_completion(self):
        test=self
        class CancelAfter(Publisher):
            def publish(self,plan):
                receipts=super().publish(plan)
                CancellationStore(test.database).request(self.claim.job_id)
                return receipts
        worker=self.worker(partial(CancelAfter,allow_root=True));target,source=await self.staged_ready(worker)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM job_operations WHERE state='STAGED'"),[(0,)])
        self.assertEqual(self.rows('SELECT state FROM staging_publications'),[('PLANNED',)])
        self.assertEqual(len(list(target.rglob('*.mkv'))),1)
        self.assertFalse(source.exists())

    async def test_retry_uses_pinned_root_after_configuration_change(self):
        class LoseConfirmation(Publisher):
            once=True
            def publish(self,plan):
                receipts=super().publish(plan)
                if type(self).once:type(self).once=False;raise OSError('lost response')
                return receipts
        worker=self.worker(partial(LoseConfirmation,allow_root=True));first,source=await self.staged_ready(worker)
        await worker.attempt()
        second=self.root/'second';second.mkdir()
        self.store.update({'storage':{'trial_root':str(second)}},expected_revision=4)
        db=connect(self.database)
        try:
            with transaction(db):db.execute("UPDATE jobs SET available_at_ms=0 WHERE kind='STAGE_TRIAL_MEDIA' AND state='RETRY_WAIT'")
        finally:db.close()
        await worker.attempt()
        self.assertEqual(self.rows('SELECT state FROM staging_publications'),[('PUBLISHED',)])
        self.assertEqual(len(list(first.rglob('*.mkv'))),1)
        self.assertEqual(list(second.iterdir()),[])
