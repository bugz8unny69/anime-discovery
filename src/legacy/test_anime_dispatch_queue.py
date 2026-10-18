import sqlite3
import unittest
from anime_dispatch_queue import enqueue_approved, claim_next, complete

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE notifications(id INTEGER PRIMARY KEY);
        CREATE TABLE series_rejection_blocks(series_id INTEGER PRIMARY KEY);
        CREATE TABLE migration_quarantined_series(series_id INTEGER PRIMARY KEY);
        CREATE TABLE episode_approval_queue(notification_id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,decision TEXT);
        INSERT INTO series VALUES(4,'DISCOVERED');
        INSERT INTO notifications VALUES(7);
        INSERT INTO episode_approval_queue VALUES(7,4,1,2,'AUTO_APPROVED');
        """)

    def test_claim_and_completion_are_idempotent(self):
        self.assertEqual(enqueue_approved(self.db),1)
        self.assertEqual(enqueue_approved(self.db),0)
        self.assertEqual(claim_next(self.db)["episode"],2)
        self.assertIsNone(claim_next(self.db))
        complete(self.db,7,success=True)
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"DONE")

    def test_rejection_after_enqueue_prevents_claim(self):
        enqueue_approved(self.db)
        self.db.execute("INSERT INTO series_rejection_blocks VALUES(4)")
        self.assertIsNone(claim_next(self.db))

    def test_review_never_dispatches(self):
        self.db.execute("UPDATE episode_approval_queue SET decision='NEEDS_REVIEW'")
        self.assertEqual(enqueue_approved(self.db),0)

if __name__=="__main__":
    unittest.main()
