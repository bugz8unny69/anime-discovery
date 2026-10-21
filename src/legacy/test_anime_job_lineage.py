"""Offline tests: job lineage is additive and keeps series notifications intact."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_job_lineage import enqueue_linked, children
from anime_async_daemon import enqueue, claim, finish


class LineageTests(unittest.TestCase):
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

    def test_parent_child_and_series_history_preserved(self):
        identity = enqueue_linked(self.db, "identity_resolution", "notification:1",
                                  json.dumps({"notification_id": self.nid}),
                                  origin_notification_id=self.nid, now=100)
        catchup = enqueue_linked(self.db, "series_gap_search", "series:1:1",
                                 '{"season":1}', parent_job_id=identity["job_id"], now=101)
        child = enqueue_linked(self.db, "claimed_acquisition", "episode:1:1",
                               '{"episode":1}', parent_job_id=catchup["job_id"], now=102)
        self.assertEqual(child["root_job_id"], identity["job_id"])
        self.assertEqual(child["origin_notification_id"], self.nid)
        self.assertEqual(children(self.db, identity["job_id"])[0][0], catchup["job_id"])
        self.assertEqual(self.db.execute("SELECT status FROM notifications WHERE id=?",
                                         (self.nid,)).fetchone()[0], "UNTRUSTED")
        job = claim(self.db, now=103)
        finish(self.db, job["id"], job["lease_token"], "DONE", now=103)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)

    def test_idempotent_child_and_conflicting_lineage_fail_closed(self):
        root = enqueue_linked(self.db, "identify", "notification:1", "{}",
                              origin_notification_id=self.nid)
        first = enqueue_linked(self.db, "search", "series:1", "{}",
                               parent_job_id=root["job_id"])
        second = enqueue_linked(self.db, "search", "series:1", "{}",
                                parent_job_id=root["job_id"])
        self.assertFalse(second["created"])
        self.assertEqual(first["job_id"], second["job_id"])
        with self.assertRaisesRegex(ValueError, "payload differs"):
            enqueue_linked(self.db, "search", "series:1", '{"different":true}',
                           parent_job_id=root["job_id"])
        with self.assertRaisesRegex(ValueError, "lineage conflicts"):
            enqueue_linked(self.db, "search", "series:1", "{}")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 2)

    def test_orphan_parent_and_missing_notification_do_not_create_jobs(self):
        with self.assertRaisesRegex(ValueError, "Parent job"):
            enqueue_linked(self.db, "search", "x", "{}", parent_job_id=999)
        with self.assertRaisesRegex(ValueError, "Origin notification"):
            enqueue_linked(self.db, "identify", "x", "{}", origin_notification_id=999)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 0)

    def test_legacy_job_unchanged(self):
        enqueue(self.db, "legacy", "existing", "{}")
        root = enqueue_linked(self.db, "legacy", "existing", "{}")
        self.assertFalse(root["created"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0], 1)

    def test_recovery_after_repeating_same_child_submission(self):
        root = enqueue_linked(self.db, "identify", "notification:1", "{}",
                              origin_notification_id=self.nid)
        child = enqueue_linked(self.db, "search", "series:1", "{}",
                               parent_job_id=root["job_id"])
        leased = claim(self.db, now=100)
        finish(self.db, leased["id"], leased["lease_token"], "DONE", now=100)
        again = enqueue_linked(self.db, "search", "series:1", "{}",
                               parent_job_id=root["job_id"])
        self.assertEqual(child["job_id"], again["job_id"])
        self.assertFalse(again["created"])


if __name__ == "__main__":
    unittest.main()
