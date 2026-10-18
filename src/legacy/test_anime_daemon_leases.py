"""Lease fencing and renewal tests for the asynchronous scheduler."""
import sqlite3
import unittest
from anime_async_daemon import enqueue, claim, renew, finish

class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        enqueue(self.db,"identity","notification:42","{}")

    def test_renew_prevents_reclaim(self):
        first=claim(self.db,now=1000,lease_seconds=30)
        renew(self.db,first["id"],first["lease_token"],now=1020,lease_seconds=30)
        self.assertIsNone(claim(self.db,now=1040,lease_seconds=30))
        self.assertIsNotNone(claim(self.db,now=1051,lease_seconds=30))

    def test_stale_token_cannot_renew_or_finish(self):
        first=claim(self.db,now=1000,lease_seconds=30)
        second=claim(self.db,now=1031,lease_seconds=30)
        with self.assertRaises(ValueError):
            renew(self.db,first["id"],first["lease_token"],now=1032)
        with self.assertRaises(ValueError):
            finish(self.db,first["id"],first["lease_token"],"DONE",now=1032)
        finish(self.db,second["id"],second["lease_token"],"DONE",now=1032)

    def test_expired_lease_cannot_renew(self):
        first=claim(self.db,now=1000,lease_seconds=30)
        with self.assertRaises(ValueError):
            renew(self.db,first["id"],first["lease_token"],now=1031)

if __name__=="__main__":
    unittest.main()
