"""Offline storage tests for operator-requested safe review retries."""
from pathlib import Path
import tempfile
import unittest

from src.nextgen.storage.review_retry import (
    RetryNotAllowed, RetryStale, request_review_retry,
)
from src.nextgen.storage.sqlite import connect, initialize, accept_event_and_job, transaction


class ReviewRetryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "jobs.sqlite"
        db = connect(self.path)
        initialize(db)
        self.event, self.job = accept_event_and_job(
            db, "test", b'{"release_name":"Test S01E01"}',
            kind="VERIFY_RELEASE", payload={"anidb_id":123})
        with transaction(db):
            db.execute("UPDATE jobs SET state='NEEDS_REVIEW',attempt_count=1,"
                       "last_reason_code='RELEASE_EPISODE_MAPPING_MISSING' WHERE job_id=?", (self.job,))
        db.close()

    def rows(self, sql, params=()):
        db = connect(self.path)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()

    def request(self, attempt=1, reason="RELEASE_EPISODE_MAPPING_MISSING"):
        return request_review_retry(
            self.path, self.job, expected_attempt=attempt,
            expected_reason=reason, clock=lambda: 12345678)

    def test_atomic_retry_and_idempotent_repeat(self):
        receipt = self.request()
        self.assertEqual((receipt.job_id, receipt.attempt, receipt.outcome),
                         (self.job, 1, "QUEUED"))
        self.assertEqual(self.rows(
            "SELECT state,attempt_count,available_at_ms,last_reason_code,activity_code "
            "FROM jobs WHERE job_id=?", (self.job,)),
            [("PENDING", 1, 12345678, None, None)])
        again = self.request()
        self.assertEqual((again.outcome, again.history_id),
                         ("ALREADY_QUEUED", receipt.history_id))
        self.assertEqual(self.rows(
            "SELECT count(*) FROM job_history WHERE job_id=? AND event_code='RETRY_REQUESTED'",
            (self.job,)), [(1,)])
        self.assertEqual(self.rows(
            "SELECT component,details_json FROM job_history WHERE history_id=?",
            (receipt.history_id,)), [("api", '{"attempt":1}')])

    def test_stale_attempt_and_changed_reason_preserve_review(self):
        for attempt, reason in ((2, "RELEASE_EPISODE_MAPPING_MISSING"),
                                (1, "RELEASE_MAPPING_MISSING")):
            with self.subTest(attempt=attempt, reason=reason), self.assertRaises(RetryStale):
                self.request(attempt, reason)
        self.assertEqual(self.rows(
            "SELECT state,last_reason_code FROM jobs WHERE job_id=?", (self.job,)),
            [("NEEDS_REVIEW", "RELEASE_EPISODE_MAPPING_MISSING")])

    def test_done_running_and_external_kinds_cannot_be_requeued(self):
        for state in ("DONE", "RUNNING", "CANCELED", "ON_HOLD", "RETRY_WAIT"):
            db=connect(self.path)
            with transaction(db):
                db.execute("UPDATE jobs SET state=? WHERE job_id=?", (state,self.job))
            db.close()
            with self.subTest(state=state), self.assertRaises(RetryNotAllowed):
                self.request()
        db=connect(self.path)
        with transaction(db):
            db.execute("UPDATE jobs SET state='NEEDS_REVIEW',kind='DOWNLOAD_TORRENT' WHERE job_id=?",
                       (self.job,))
        db.close()
        with self.assertRaises(RetryNotAllowed):
            self.request()

    def test_canceled_operation_or_child_blocks_retry(self):
        db=connect(self.path)
        with transaction(db):
            op=db.execute("SELECT operation_id FROM job_operation_members WHERE job_id=?",
                          (self.job,)).fetchone()[0]
            db.execute("UPDATE job_operations SET state='CANCELED',"
                       "cleanup_state='COMPLETE',reason_code='CANCELLATION_COMPLETE' "
                       "WHERE operation_id=?",(op,))
        db.close()
        with self.assertRaises(RetryNotAllowed):
            self.request()
        db=connect(self.path)
        with transaction(db):
            db.execute("UPDATE job_operations SET state='ACTIVE',cleanup_state='NONE',"
                       "reason_code=NULL WHERE operation_id=?", (op,))
            db.execute("INSERT INTO jobs(event_id,created_by_job_id,kind,payload_json,state,"
                       "available_at_ms,created_at_ms,updated_at_ms) "
                       "VALUES(?,?,'EVALUATE_TRIAL','{}','DONE',1,1,1)",(self.event,self.job))
        db.close()
        with self.assertRaises(RetryNotAllowed):
            self.request()


if __name__ == "__main__":
    unittest.main()
