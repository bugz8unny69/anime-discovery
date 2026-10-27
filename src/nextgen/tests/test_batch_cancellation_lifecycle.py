"""Safety proofs for batch cancellation cleanup and reservation release.

No external qBittorrent calls. Synthetic DB contracts ensure a batch torrent
cannot release a reservation until its own one-shot cleanup is complete.
"""
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src.nextgen.cancellation import CancellationError
from src.nextgen.cancellation_service import CancellationService
from src.nextgen.storage.reservation_release import validate_releasable, release_cancelled


class BatchCancellationReleaseTests(unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE jobs(job_id INTEGER,state TEXT,kind TEXT,
                created_by_job_id INTEGER,payload_json TEXT);
            CREATE TABLE job_operation_members(operation_id INTEGER,job_id INTEGER);
            CREATE TABLE episode_reservations(evaluation_job_id INTEGER,
                owner_job_id INTEGER,state TEXT);
            CREATE TABLE batch_episode_reservations(
                reservation_id INTEGER,plan_id INTEGER,owner_job_id INTEGER,state TEXT,
                ended_at_ms INTEGER,ended_by_job_id INTEGER);
            CREATE TABLE batch_trial_plans(plan_id INTEGER,evaluation_job_id INTEGER);
            CREATE TABLE batch_torrent_submissions(plan_id INTEGER);
            CREATE TABLE batch_cancellation_cleanup(
                plan_id INTEGER,operation_id INTEGER,phase TEXT);
            CREATE TABLE staging_publications(job_id INTEGER,state TEXT);
            CREATE TABLE batch_staging_publications(job_id INTEGER,state TEXT);
            CREATE TABLE job_operations(operation_id INTEGER,state TEXT,
                cleanup_state TEXT);
            CREATE TABLE acquisition_plans(plan_id INTEGER,reservation_id INTEGER);
            CREATE TABLE job_history(job_id INTEGER);
            INSERT INTO jobs VALUES(51,'DONE','RESERVE_BATCH',NULL,'{}');
            INSERT INTO job_operation_members VALUES(7,51);
            INSERT INTO batch_trial_plans VALUES(15,42);
            INSERT INTO batch_episode_reservations VALUES
                (23,15,51,'ACTIVE',NULL,NULL);
            INSERT INTO batch_torrent_submissions VALUES(15);
            INSERT INTO job_operations VALUES(7,'CANCELED','COMPLETE');
        """)
        self.db=db

    def test_without_proof_batch_reservation_stays_active(self):
        with self.assertRaises(CancellationError):
            validate_releasable(self.db,7)
        self.db.execute(
            "INSERT INTO batch_cancellation_cleanup VALUES(15,8,'COMPLETE')")
        with self.assertRaises(CancellationError):
            validate_releasable(self.db,7)
        self.db.execute(
            "UPDATE batch_cancellation_cleanup SET operation_id=7,phase='FILES'")
        with self.assertRaises(CancellationError):
            validate_releasable(self.db,7)

    def test_matching_completed_batch_cleanup_allows_release(self):
        self.db.execute(
            "INSERT INTO batch_cancellation_cleanup VALUES(15,7,'COMPLETE')")
        validate_releasable(self.db,7)
        # No journal recreation or new stop/remove permit is required.
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM batch_episode_reservations WHERE state='RELEASED'"
        ).fetchone())

    def test_partial_published_batch_is_never_released(self):
        self.db.execute(
            "INSERT INTO batch_cancellation_cleanup VALUES(15,7,'COMPLETE')")
        self.db.execute("INSERT INTO jobs VALUES(61,'DONE','STAGE_BATCH_EPISODE',NULL,'{}')")
        self.db.execute('INSERT INTO job_operation_members VALUES(7,61)')
        self.db.execute("INSERT INTO batch_staging_publications VALUES(61,'PUBLISHED')")
        with self.assertRaises(CancellationError):
            release_cancelled(self.db,7,51,1000,component='worker')


class BatchCancellationOrchestrationTests(unittest.TestCase):
    def test_existing_cleaner_reused_after_restart_without_repeating_complete_target(self):
        class Queue:
            database=':memory:'
            def connection(self):
                from contextlib import nullcontext
                return nullcontext(SimpleNamespace(
                    execute=lambda sql,args=():SimpleNamespace(
                        fetchone=lambda:('COMPLETE',))))
        obj=CancellationService.__new__(CancellationService)
        obj.store=SimpleNamespace(queue=Queue(),
             status=lambda job_id:dict(operation_id=7,can_cleanup=True))
        obj.database=':memory:'
        obj._admission=lambda: __import__('contextlib').nullcontext()
        obj._targets=lambda job_id:(7,[],[
            SimpleNamespace(plan=SimpleNamespace(plan_id=15))])
        obj._state=lambda *args,**kwargs:None
        obj._fence=lambda *args,**kwargs:None
        with (patch('src.nextgen.cancellation_service.OperationGate') as gate,
              patch('src.nextgen.batch_cancellation_cleanup.BatchCanceledCleanup')
              as cleaner,
              patch('src.nextgen.staging_artifacts.clean_temporaries')):
            gate.return_value.hold.return_value.__enter__.return_value=None
            result=obj.cleanup(51)
            self.assertEqual(result['operation_id'],7)
            cleaner.return_value._clean_target.assert_not_called()
