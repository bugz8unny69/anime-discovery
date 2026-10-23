"""Offline durable action admission, duplicate clicks and control recovery; unexecuted."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest
from unittest.mock import patch

from src.nextgen.cancellation import OperationGate
from src.nextgen.job_contracts import Policy, Registry
from src.nextgen.jobs.cleanup_canceled_operation_job import registration as cleanup
from src.nextgen.jobs.keep_media_job import registration as keep
from src.nextgen.storage.cancellation import CancellationStore
from src.nextgen.storage.job_queue import JobQueue, LeaseLost
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable
from src.nextgen.storage.sqlite import connect, enqueue_job, transaction
from src.nextgen.tests import test_acquisition_preparation as fixture
from src.nextgen.worker import Worker


class ManagementActionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.AcquisitionPreparationTests.asyncSetUp
    rows=fixture.AcquisitionPreparationTests.rows

    def add(self):
        db=connect(self.database)
        try:
            with transaction(db):return enqueue_job(db,kind='TASK',payload={},component='api',available_at_ms=0)
        finally:db.close()

    def actions(self):return ManagementActions(self.database)

    def staged(self):
        # Synthetic contract fixture, never a claim of real filesystem staging.
        job=self.add();db=connect(self.database)
        try:
            with transaction(db):
                db.execute("UPDATE jobs SET state='DONE' WHERE job_id=?",(job,))
                db.execute("UPDATE job_operations SET state='STAGED' WHERE operation_id=(SELECT operation_id FROM job_operation_members WHERE job_id=?)",(job,))
        finally:db.close()
        return job

    async def test_pending_cancel_finishes_locally_without_a_control_job(self):
        job=self.add()
        status,data,_=self.actions().submit(job,'cancel')
        self.assertEqual(status,200);self.assertTrue(data['completed'])
        self.assertEqual(self.rows('SELECT action FROM management_actions'),[])
        self.assertEqual(self.rows('SELECT state FROM jobs'),[('CANCELED',)])
        self.assertEqual(self.actions().submit(job,'cancel')[0],200)

    async def test_running_cancel_is_atomic_with_distinct_cleanup_scope_and_deduplicates(self):
        target=self.add();queue=JobQueue(self.database);claim,_=queue.claim()
        status,data,_=self.actions().submit(target,'cancel')
        self.assertEqual(status,202);control=data['job_id']
        self.assertNotEqual(target,control)
        self.assertEqual(self.rows('SELECT state FROM job_operations ORDER BY operation_id'),[('CANCEL_REQUESTED',),('ACTIVE',)])
        self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(target,)),[('RUNNING',)])
        for action in ('cancel','cleanup'):
            other=self.actions().submit(target,action)[1]
            self.assertEqual(other['job_id'],control);self.assertTrue(other['reused'])
        fresh=ManagementActions(self.database)
        self.assertEqual(fresh.submit(target,'cancel')[1]['job_id'],control)
        with self.assertRaises(ActionUnavailable):fresh.submit(control,'cancel')
        self.assertFalse(CancellationStore(self.database).status(control)['can_cancel'])

    async def test_enqueue_failure_rolls_back_cancellation_and_history(self):
        target=self.add();JobQueue(self.database).claim()
        before=self.rows('SELECT * FROM job_history')
        with patch('src.nextgen.storage.management_actions.enqueue_job_with_receipt',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.actions().submit(target,'cancel')
        self.assertEqual(self.rows('SELECT state FROM job_operations'),[('ACTIVE',)])
        self.assertEqual(self.rows('SELECT * FROM job_history'),before)
        self.assertEqual(self.rows('SELECT * FROM management_actions'),[])

    async def test_concurrent_keep_requests_share_one_receipt(self):
        first=self.staged()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.actions().submit(first,'keep'),range(2)))
        self.assertEqual(results[0][1]['job_id'],results[1][1]['job_id'])
        self.assertEqual(self.rows('SELECT count(*) FROM management_actions'),[(1,)])

    async def test_keep_requires_staged_and_stays_explicitly_blocked_without_media_library(self):
        pending=self.add()
        with self.assertRaises(ActionUnavailable):self.actions().submit(pending,'keep')
        self.actions().submit(pending,'cancel')
        target=self.staged();_,data,_=self.actions().submit(target,'keep')
        worker=Worker(self.store,self.startup,Registry((keep(),)))
        self.addAsyncCleanup(worker.close)
        await worker.attempt()
        self.assertEqual(self.rows('SELECT state,last_reason_code FROM jobs WHERE job_id=?',(data['job_id'],)),[('BLOCKED','KEEP_NOT_READY')])
        self.assertEqual(self.actions().submit(target,'keep')[1]['job_id'],data['job_id'])
        self.assertEqual(self.rows('SELECT state FROM job_operations WHERE operation_id=(SELECT operation_id FROM job_operation_members WHERE job_id=?)',(target,)),[('STAGED',)])

    async def test_cleanup_waits_for_target_lock_then_completes_after_drain(self):
        target=self.add();queue=JobQueue(self.database);claim,_=queue.claim()
        scope=queue.operation_id(claim)
        _,data,_=self.actions().submit(target,'cancel')
        worker=Worker(self.store,self.startup,Registry((cleanup(object()),)))
        self.addAsyncCleanup(worker.close)
        with OperationGate(self.database).hold(scope):
            await worker.attempt()
            self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(data['job_id'],)),[('RETRY_WAIT',)])
            self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(target,)),[('RUNNING',)])
        db=connect(self.database)
        try:
            with transaction(db):db.execute('UPDATE jobs SET available_at_ms=0 WHERE job_id=?',(data['job_id'],))
        finally:db.close()
        await worker.attempt()
        self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(data['job_id'],)),[('DONE',)])
        self.assertEqual(CancellationStore(self.database).status(target)['cleanup_state'],'COMPLETE')
        self.assertEqual(self.rows("SELECT count(*) FROM job_history WHERE job_id=? AND event_code='RETRY_SCHEDULED'",(data['job_id'],)),[(0,)])

    async def test_stale_control_lease_cannot_mutate_target(self):
        target=self.add();JobQueue(self.database).claim()
        _,data,_=self.actions().submit(target,'cancel')
        real_queue=JobQueue(self.database);claim,_=real_queue.claim()
        self.assertEqual(claim.job_id,data['job_id'])
        db=connect(self.database)
        try:
            with transaction(db):db.execute('UPDATE jobs SET lease_expires_at_ms=0 WHERE job_id=?',(claim.job_id,))
        finally:db.close()
        with self.assertRaises(LeaseLost):self.actions().bind(claim,'CLEANUP')
        self.assertEqual(CancellationStore(self.database).status(target)['state'],'CANCEL_REQUESTED')

    async def test_expired_cleanup_job_recovers_same_action_without_duplicate_enqueue(self):
        target=self.add();queue=JobQueue(self.database);queue.claim()
        _,data,_=self.actions().submit(target,'cancel');queue.claim()
        db=connect(self.database)
        try:
            with transaction(db):db.execute("UPDATE jobs SET lease_expires_at_ms=0 WHERE state='RUNNING'")
        finally:db.close()
        queue.recover_expired()
        self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(target,)),[('CANCELED',)])
        self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(data['job_id'],)),[('RETRY_WAIT',)])
        self.assertEqual(self.actions().submit(target,'cleanup')[1]['job_id'],data['job_id'])
        self.assertEqual(self.rows('SELECT count(*) FROM management_actions'),[(1,)])

    async def test_expired_guard_prevents_cleanup_state_changes_even_inside_exclusive_target_gate(self):
        from src.nextgen.cancellation_service import CancellationService
        target=self.add();queue=JobQueue(self.database);queue.claim()
        _,data,_=self.actions().submit(target,'cancel');claim,_=queue.claim()
        db=connect(self.database)
        try:
            with transaction(db):db.execute('UPDATE jobs SET lease_expires_at_ms=0 WHERE job_id=?',(claim.job_id,))
        finally:db.close()
        def guard(db):queue._owns(db,claim,queue.now())
        service=CancellationService(self.startup,object(),admitted=True,guard=guard,component='worker')
        with self.assertRaises(LeaseLost):service.cleanup(target)
        self.assertEqual(self.rows('SELECT state FROM jobs WHERE job_id=?',(target,)),[('RUNNING',)])
        self.assertEqual(CancellationStore(self.database).status(target)['state'],'CANCEL_REQUESTED')

    async def test_explicit_cleanup_after_review_resumes_same_job_but_pending_clicks_do_not(self):
        target=self.add();JobQueue(self.database).claim()
        _,data,_=self.actions().submit(target,'cancel')
        db=connect(self.database)
        try:
            with transaction(db):
                db.execute("UPDATE jobs SET state='NEEDS_REVIEW',last_reason_code='CANCELLATION_REVIEW' WHERE job_id=?",(data['job_id'],))
                db.execute("UPDATE job_operations SET state='CANCELED',cleanup_state='REVIEW',reason_code='CANCELLATION_REVIEW' WHERE operation_id=(SELECT operation_id FROM job_operation_members WHERE job_id=?)",(target,))
        finally:db.close()
        _,resumed,_=self.actions().submit(target,'cleanup')
        self.assertTrue(resumed['resumed']);self.assertEqual(resumed['job_id'],data['job_id'])
        _,duplicate,_=self.actions().submit(target,'cleanup')
        self.assertTrue(duplicate['reused']);self.assertNotIn('resumed',duplicate)
        self.assertEqual(self.rows("SELECT count(*) FROM job_history WHERE event_code='MANAGEMENT_ACTION_RESUMED'"),[(1,)])

    async def test_idle_database_state_does_not_bypass_a_stale_handlers_drain_lock(self):
        target=self.add();queue=JobQueue(self.database);claim,_=queue.claim()
        with OperationGate(self.database).hold(queue.operation_id(claim)):
            db=connect(self.database)
            try:
                with transaction(db):
                    db.execute("UPDATE jobs SET state='RETRY_WAIT',lease_token=NULL,lease_expires_at_ms=NULL WHERE job_id=?",(target,))
            finally:db.close()
            status,data,_=self.actions().submit(target,'cancel')
            self.assertEqual(status,202);self.assertTrue(data['job_id'])
            self.assertEqual(CancellationStore(self.database).status(target)['cleanup_state'],'PENDING')
