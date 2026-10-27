"""Offline Reject admission, selected cleanup and future Intake blocking; unrun."""
import unittest

from src.nextgen.jobs.reject_media_job import registration as reject
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests.test_stage_media_job import StageMediaJobTests
from src.nextgen.tests.test_torrent_transfer import TorrentTransferTests
from src.nextgen.tests.test_verify_media_job import VerifyMediaJobTests
from src.nextgen.tests.test_acquisition_preparation import AcquisitionPreparationTests


class RejectMediaTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=AcquisitionPreparationTests.asyncSetUp
    rows=AcquisitionPreparationTests.rows
    source=AcquisitionPreparationTests.source
    queued=TorrentTransferTests.queued
    due=TorrentTransferTests.due
    ready=VerifyMediaJobTests.ready
    staged_ready=StageMediaJobTests.staged_ready

    async def staged(self):
        worker=StageMediaJobTests.worker(self,additional=(reject(),))
        target,source=await self.staged_ready(worker)
        await worker.attempt()
        job=self.rows("SELECT job_id FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'")[0][0]
        return worker,target,job

    async def test_reject_is_durable_before_cleanup_and_duplicate_click_reuses_job(self):
        worker,target,job=await self.staged()
        actions=ManagementActions(self.database)
        status,first,_=actions.submit(job,'reject')
        _,again,_=actions.submit(job,'reject')
        self.assertEqual(status,202);self.assertEqual(first['job_id'],again['job_id'])
        self.assertTrue(again['reused'])
        self.assertEqual(self.rows('SELECT decision,cleanup_state FROM anime_review_decisions'),[('REJECT','PENDING')])
        self.assertEqual(len(list(target.rglob('*.mkv'))),1)
        await worker.attempt()
        self.assertEqual(self.rows('SELECT cleanup_state FROM anime_review_decisions'),[('COMPLETE',)])
        self.assertEqual(list(target.rglob('*.mkv')),[])
        self.assertEqual(len(list(target.rglob('tvshow.nfo'))),1)
        self.assertEqual(len(list(target.rglob('*.nfo'))),1)
        with self.assertRaises(ActionUnavailable):actions.submit(job,'keep')

    async def test_missing_receipt_is_reviewed_before_deleting_any_video(self):
        import json
        worker,target,job=await self.staged()
        video=next(target.rglob('*.mkv'))
        db=connect(self.database)
        try:
            with transaction(db):
                row=db.execute(
                    "SELECT receipts_json FROM staging_publications "
                    "WHERE state='PUBLISHED'").fetchone()
                receipts=json.loads(row[0])
                self.assertGreater(len(receipts),1)
                db.execute(
                    "UPDATE staging_publications SET receipts_json=? "
                    "WHERE state='PUBLISHED'",(json.dumps(receipts[:-1]),))
        finally:db.close()
        _,control,_=ManagementActions(self.database).submit(job,'reject')
        await worker.attempt()
        self.assertTrue(video.exists())
        self.assertEqual(self.rows(
            'SELECT cleanup_state FROM anime_review_decisions'),[('PENDING',)])
        self.assertEqual(self.rows(
            'SELECT state,last_reason_code FROM jobs WHERE job_id=?',
            (control['job_id'],)),
            [('NEEDS_REVIEW','REJECT_CLEANUP_REVIEW')])

    async def test_new_episode_for_rejected_anime_stops_before_reservation(self):
        worker,target,job=await self.staged()
        ManagementActions(self.database).submit(job,'reject');await worker.attempt()
        # Isolate this acquisition assertion from the independent follow-up job.
        db=connect(self.database)
        try:
            with transaction(db):db.execute("UPDATE jobs SET available_at_ms=9999999999999 WHERE kind='CLEANUP_DECIDED_DOWNLOAD'")
        finally:db.close()
        before=self.rows('SELECT count(*) FROM episode_reservations')
        self.source(episode=11);await worker.attempt()
        self.assertEqual(self.rows('SELECT count(*) FROM episode_reservations'),before)
        self.assertEqual(self.rows("SELECT state,last_reason_code FROM jobs WHERE kind='EVALUATE_TRIAL' ORDER BY job_id DESC LIMIT 1"),
                         [('ON_HOLD','ANIME_REJECTED')])

    async def test_changed_staged_file_is_preserved_and_existing_reject_can_resume(self):
        worker,target,job=await self.staged()
        video=next(target.rglob('*.mkv'));video.write_bytes(b'changed')
        actions=ManagementActions(self.database);_,first,_=actions.submit(job,'reject')
        await worker.attempt()
        self.assertTrue(video.exists())
        self.assertEqual(self.rows('SELECT decision,cleanup_state FROM anime_review_decisions'),[('REJECT','PENDING')])
        self.assertEqual(self.rows('SELECT state,last_reason_code FROM jobs WHERE job_id=?',(first['job_id'],)),
                         [('NEEDS_REVIEW','REJECT_CLEANUP_REVIEW')])
        _,resumed,_=actions.submit(job,'reject')
        self.assertEqual(resumed['job_id'],first['job_id']);self.assertTrue(resumed['resumed'])

    async def test_missing_selected_files_reconcile_and_unrelated_files_survive(self):
        worker,target,job=await self.staged()
        video=next(target.rglob('*.mkv'));video.unlink()
        other=target/'unrelated.txt';other.write_text('preserve')
        ManagementActions(self.database).submit(job,'reject');await worker.attempt()
        self.assertEqual(other.read_text(),'preserve')
        self.assertEqual(self.rows('SELECT cleanup_state FROM anime_review_decisions'),[('COMPLETE',)])
