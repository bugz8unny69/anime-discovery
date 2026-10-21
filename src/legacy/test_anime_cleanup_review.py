"""Offline, no-qB/no-filesystem cancellation inventory tests."""
import json
import sqlite3
import unittest

from anime_async_daemon import enqueue
from anime_cleanup_review import inventory
from anime_job_management import manage


class CleanupReviewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        enqueue(self.db, "claimed_acquisition", "7", '{"notification_id":7}')
        self.job_id = self.db.execute("SELECT id FROM daemon_jobs").fetchone()[0]
        self.db.execute("UPDATE daemon_jobs SET state='NEEDS_REVIEW'")

    def test_no_proven_resources_never_claims_cleanup(self):
        result = manage(self.db, self.job_id, "cancel",
                        expected_state="NEEDS_REVIEW", expected_attempts=0)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(self.db.execute(
            "SELECT status,candidate_hashes_json FROM daemon_job_cleanup_review"
        ).fetchone(), ("NOT_VERIFIED", "[]"))
        self.assertFalse(inventory(self.db, "claimed_acquisition", "7")["may_delete"])

    def test_candidate_hash_does_not_grant_delete_permission(self):
        h = "a" * 40
        self.db.execute("""CREATE TABLE torrent_recovery_records
            (notification_id INTEGER,infohash TEXT)""")
        self.db.execute("INSERT INTO torrent_recovery_records VALUES (?,?)", (7, h))
        self.db.execute("""CREATE TABLE qb_torrent_ownership
            (infohash TEXT,status TEXT)""")
        self.db.execute("INSERT INTO qb_torrent_ownership VALUES (?,?)", (h, "OWNED"))
        preview = inventory(self.db, "claimed_acquisition", "7")
        self.assertEqual(preview["candidate_hashes"], [h])
        self.assertEqual(preview["ownership"][h], "OWNED")
        self.assertFalse(preview["may_delete"])
        manage(self.db, self.job_id, "cancel",
               expected_state="NEEDS_REVIEW", expected_attempts=0)
        status, raw = self.db.execute(
            "SELECT status,candidate_hashes_json FROM daemon_job_cleanup_review"
        ).fetchone()
        self.assertEqual(status, "REVIEW_REQUIRED")
        self.assertEqual(json.loads(raw), [h])
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_jobs").fetchone()[0], "BLOCKED")

    def test_malformed_hash_not_accepted(self):
        self.db.execute("""CREATE TABLE torrent_recovery_records
            (notification_id INTEGER,infohash TEXT)""")
        self.db.execute(
            "INSERT INTO torrent_recovery_records VALUES (7,'not-a-hash')")
        self.assertEqual(inventory(
            self.db, "claimed_acquisition", "7")["candidate_hashes"], [])


if __name__ == "__main__":
    unittest.main()
