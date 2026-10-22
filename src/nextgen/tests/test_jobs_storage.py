"""Offline tests for independent NextGen jobs; no running worker or services."""
import os
import tempfile
import unittest

from src.nextgen.storage.sqlite import (
    connect, initialize, enqueue_job, accept_event_and_job
)


class JobsStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(os.path.join(self.tmp.name, "jobs.sqlite"))
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_intake_commits_event_and_first_job(self):
        event_id, job_id = accept_event_and_job(
            self.db, "autobrr", b"raw", kind="identity", payload={"release": "a"})
        record = self.db.execute(
            "SELECT event_id,created_by_job_id,state FROM jobs WHERE job_id=?",
            (job_id,)).fetchone()
        self.assertEqual(record, (event_id, None, "PENDING"))

    def test_independent_successor_has_only_provenance_reference(self):
        event, first = accept_event_and_job(
            self.db, "autobrr", b"raw", kind="identity", payload={})
        with self.db:
            successor = enqueue_job(
                self.db, event_id=event, created_by_job_id=first,
                kind="next_stage", payload={"ready": True})
        self.assertEqual(self.db.execute(
            "SELECT created_by_job_id FROM jobs WHERE job_id=?",
            (successor,)).fetchone()[0], first)
        self.assertEqual(self.db.execute(
            "SELECT state FROM jobs WHERE job_id=?",
            (successor,)).fetchone()[0], "PENDING")

    def test_rollback_discards_successor(self):
        event, first = accept_event_and_job(
            self.db, "autobrr", b"raw", kind="identity", payload={})
        try:
            with self.db:
                enqueue_job(self.db, event_id=event, created_by_job_id=first,
                            kind="next_stage", payload={})
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_unknown_job_source_rejected(self):
        with self.assertRaises(Exception):
            with self.db:
                enqueue_job(self.db, created_by_job_id=999,
                            kind="identity", payload={})


if __name__ == "__main__":
    unittest.main()
