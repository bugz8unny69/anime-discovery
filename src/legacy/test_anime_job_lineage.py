"""Offline tests: independent handoffs preserve notification history."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_job_lineage import enqueue_linked, triggered_jobs
from anime_async_daemon import enqueue, claim, finish


class HandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "queue.sqlite"
        initialize(path)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.db.execute("""INSERT INTO notifications
            (source,release_name,source_guid,info_hash,received_at)
            VALUES ('autobrr','Example S01E10','event:10',?,123)""", ("a" * 40,))
        self.nid = self.db.execute("SELECT id FROM notifications").fetchone()[0]

    def test_independent_jobs_and_series_history_preserved(self):
        identity = enqueue_linked(self.db, "identity", "notification:1", "{}",
                                  notification_id=self.nid, now=100)
        search = enqueue_linked(self.db, "series_gap_search", "series:1:1",
                                '{"season":1}', triggered_by_job_id=identity["job_id"],
                                notification_id=self.nid, now=101)
        acquire = enqueue_linked(self.db, "claimed_acquisition", "episode:1",
                                 '{"episode":1}', triggered_by_job_id=search["job_id"],
                                 notification_id=self.nid, now=102)
        self.assertEqual(acquire["triggered_by_job_id"], search["job_id"])
        self.assertEqual(triggered_jobs(self.db, identity["job_id"])[0][0], search["job_id"])
        # Identity completion has no dependency on its successor.
        job = claim(self.db, now=103)
        self.assertEqual(job["id"], identity["job_id"])
        finish(self.db, job["id"], job["lease_token"], "DONE", now=103)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_jobs WHERE id=?", (search["job_id"],)).fetchone()[0], "READY")
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?", (self.nid,)).fetchone()[0], "UNTRUSTED")

    def test_dedup_first_trigger_wins_even_with_multiple_initiators(self):
        first = enqueue_linked(self.db, "identity", "n1", "{}",
                               notification_id=self.nid)
        second = enqueue_linked(self.db, "identity", "n2", "{}",
                                notification_id=self.nid)
        a = enqueue_linked(self.db, "search", "same-season", "{}",
                           triggered_by_job_id=first["job_id"])
        b = enqueue_linked(self.db, "search", "same-season", "{}",
                           triggered_by_job_id=second["job_id"])
        self.assertEqual(a["job_id"], b["job_id"])
        self.assertFalse(b["created"])
        self.assertEqual(b["triggered_by_job_id"], first["job_id"])
        with self.assertRaisesRegex(ValueError, "payload differs"):
            enqueue_linked(self.db, "search", "same-season", '{"different":true}')
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 3)

    def test_missing_trigger_and_notification_roll_back(self):
        with self.assertRaisesRegex(ValueError, "Triggering job not found"):
            enqueue_linked(self.db, "search", "x", "{}", triggered_by_job_id=999)
        with self.assertRaisesRegex(ValueError, "Notification not found"):
            enqueue_linked(self.db, "identify", "x", "{}", notification_id=999)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 0)

    def test_legacy_job_is_not_recreated(self):
        enqueue(self.db, "legacy", "existing", "{}")
        reused = enqueue_linked(self.db, "legacy", "existing", "{}")
        self.assertFalse(reused["created"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 1)

    def test_retry_does_not_requeue_existing_job(self):
        root = enqueue_linked(self.db, "identity", "n1", "{}")
        child = enqueue_linked(self.db, "search", "series:1", "{}",
                               triggered_by_job_id=root["job_id"])
        job = claim(self.db, now=100)
        finish(self.db, job["id"], job["lease_token"], "DONE", now=100)
        again = enqueue_linked(self.db, "search", "series:1", "{}",
                               triggered_by_job_id=root["job_id"])
        self.assertEqual(again["job_id"], child["job_id"])
        self.assertFalse(again["created"])


if __name__ == "__main__":
    unittest.main()
