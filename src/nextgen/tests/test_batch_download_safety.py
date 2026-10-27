"""Offline pinned-root and cleanup-gate protection checks."""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.nextgen.batch_decision_cleanup import (
    BatchDecisionCleanup, protected_staging_roots,
)
from src.nextgen.cancellation import CancellationError, CleanupBusy
from src.nextgen.jobs.cleanup_batch_download_job import registration


class BatchDownloadSafetyTests(unittest.TestCase):
    def test_pinned_staging_roots_are_all_protected_across_configuration_changes(self):
        publications=(
            (10,1,json.dumps({'root':'/old/staging','transfer':'COPY'})),
            (10,2,json.dumps({'root':'/new/staging','transfer':'COPY'})),
            (10,3,json.dumps({'root':'/old/staging','transfer':'COPY'})),
        )
        self.assertEqual(protected_staging_roots(publications),
                         ('/new/staging','/old/staging'))

    def test_missing_or_non_copy_staging_origin_blocks_cleanup(self):
        for rows in (
            (), ((10,1,'not json'),),
            ((10,1,json.dumps({'root':'/stage','transfer':'MOVE'})),),
            ((10,1,json.dumps({'transfer':'COPY'})),),
        ):
            with self.subTest(rows=rows),self.assertRaises(CancellationError):
                protected_staging_roots(rows)

    def test_cancelled_attempt_is_fenced_before_database_mutation(self):
        service=BatchDecisionCleanup.__new__(BatchDecisionCleanup)
        service.cancelled=threading.Event()
        service.cancelled.set()
        with self.assertRaises(CancellationError):
            service._fence()


class BatchDownloadBusyTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_lock_contention_defers_instead_of_failing_cleanup(self):
        async def reader(digest,configuration,cancelled):
            return b'metainfo'
        class Service:
            def __init__(self,configuration,secrets):
                pass
            def source_hash(self,claim,decision):
                return 'a'*40
            def run(self,claim,decision,inventory,cancelled):
                raise CleanupBusy()
        context=SimpleNamespace(
            data=lambda:{'decision_job_id':123},
            claim=SimpleNamespace(job_id=124),
            cancelled=threading.Event(),
            configuration=object(),
        )
        with patch('src.nextgen.jobs.cleanup_batch_download_job.parse_batch_metainfo',
                   return_value=SimpleNamespace(info_hash='a'*40)):
            result=await registration(reader,object(),service_factory=Service).execute(
                context)
        self.assertEqual((result.kind,result.reason_code,result.delay_ms),
                         ('defer','DECISION_DOWNLOAD_CLEANUP_WAITING',1000))
