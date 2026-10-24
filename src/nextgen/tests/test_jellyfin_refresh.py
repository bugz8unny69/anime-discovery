"""Offline durable Jellyfin refresh handoff for staged media; unrun."""
import unittest

from src.nextgen.jobs.keep_media_job import registration as keep
from src.nextgen.jobs.refresh_jellyfin_job import registration as refresh
from src.nextgen.jellyfin import JellyfinUnavailable
from src.nextgen.storage.sqlite import connect,transaction
from src.nextgen.tests.test_stage_media_job import StageMediaJobTests
from src.nextgen.tests.test_acquisition_preparation import AcquisitionPreparationTests


class Secrets:
    def jellyfin_api_key(self):return "abcdef0123456789"


class FakeJellyfin:
    calls=0
    fail=False
    def __init__(self,options):
        assert options.base_url=="https://jellyfin.internal"
        assert options.api_key=="abcdef0123456789"
    def request_scan(self):
        type(self).calls+=1
        if type(self).fail:raise JellyfinUnavailable()


class JellyfinRefreshTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=AcquisitionPreparationTests.asyncSetUp
    rows=AcquisitionPreparationTests.rows
    source=AcquisitionPreparationTests.source
    ready=StageMediaJobTests.ready
    queued=StageMediaJobTests.queued
    due=StageMediaJobTests.due
    worker=StageMediaJobTests.worker
    staged_ready=StageMediaJobTests.staged_ready

    async def make_staged(self,*,enabled):
        FakeJellyfin.calls=0;FakeJellyfin.fail=False
        worker=self.worker(additional=(refresh(Secrets(),client_factory=FakeJellyfin),),
                           refresh_kind="REFRESH_JELLYFIN")
        self.addAsyncCleanup(worker.close)
        target,_=await self.staged_ready(worker)
        if enabled:
            self.store.update({"jellyfin":{"base_url":"https://jellyfin.internal"}},expected_revision=4)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'"),[("DONE",)])
        self.assertEqual(self.rows("SELECT state FROM job_operations WHERE operation_id="
            "(SELECT operation_id FROM job_operation_members WHERE job_id="
            "(SELECT job_id FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'))"),[("STAGED",)])
        return worker,target

    async def test_scan_is_queued_after_staging_in_independent_operation(self):
        worker,target=await self.make_staged(enabled=True)
        self.assertEqual(FakeJellyfin.calls,0)
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='REFRESH_JELLYFIN'"),[("PENDING",)])
        op=self.rows("SELECT m.operation_id FROM job_operation_members m JOIN jobs j USING(job_id) "
                     "WHERE j.kind='REFRESH_JELLYFIN'")[0][0]
        stage_op=self.rows("SELECT m.operation_id FROM job_operation_members m JOIN jobs j USING(job_id) "
                           "WHERE j.kind='STAGE_TRIAL_MEDIA'")[0][0]
        self.assertNotEqual(op,stage_op)
        await worker.attempt()
        self.assertEqual(FakeJellyfin.calls,1)
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='REFRESH_JELLYFIN'"),[("DONE",)])
        self.assertEqual(len(list(target.rglob("*.mkv"))),1)

    async def test_without_jellyfin_config_no_job_or_network(self):
        worker,target=await self.make_staged(enabled=False)
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind='REFRESH_JELLYFIN'"),[(0,)])
        self.assertEqual(FakeJellyfin.calls,0)
        self.assertEqual(len(list(target.rglob("*.mkv"))),1)

    async def test_refresh_error_retries_independently_without_replaying_staging(self):
        worker,target=await self.make_staged(enabled=True)
        FakeJellyfin.fail=True
        await worker.attempt()
        self.assertEqual(FakeJellyfin.calls,1)
        self.assertEqual(self.rows("SELECT state,last_reason_code FROM jobs WHERE kind='REFRESH_JELLYFIN'"),
                         [("RETRY_WAIT","JELLYFIN_REFRESH_UNAVAILABLE")])
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'"),[("DONE",)])
        FakeJellyfin.fail=False
        db=connect(self.database)
        try:
            with transaction(db):
                db.execute("UPDATE jobs SET available_at_ms=0 WHERE kind='REFRESH_JELLYFIN'")
        finally:db.close()
        await worker.attempt()
        self.assertEqual(FakeJellyfin.calls,2)
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='REFRESH_JELLYFIN'"),[("DONE",)])
        self.assertEqual(len(list(target.rglob("*.mkv"))),1)

    def test_keep_schedules_only_after_success_and_uses_separate_scope(self):
        spec=keep(None,refresh_kind="REFRESH_JELLYFIN")
        selected=spec.route({"proof":{},"source_job_id":42,"refresh_required":True})
        self.assertEqual(len(selected),1)
        self.assertTrue(selected[0].independent)
        self.assertEqual(selected[0].kind,"REFRESH_JELLYFIN")
        self.assertEqual(spec.route({"proof":{},"source_job_id":42,"refresh_required":False}),())


if __name__=="__main__":unittest.main()
