import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_async_daemon import enqueue,claim,finish

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=sqlite3.connect(Path(self.temp.name)/"queue.db",isolation_level=None)
        self.addCleanup(self.db.close)

    def test_unique_jobs_and_retry(self):
        enqueue(self.db,"identify","notification:1","{}")
        enqueue(self.db,"identify","notification:1","{}")
        job=claim(self.db,now=100)
        self.assertIsNotNone(job)
        self.assertIsNone(claim(self.db,now=101))
        finish(self.db,job["id"],job["lease_token"],"DEFERRED",now=100)
        self.assertIsNone(claim(self.db,now=101))
        retry=claim(self.db,now=106)
        self.assertEqual(retry["id"],job["id"])
        finish(self.db,retry["id"],retry["lease_token"],"DONE",now=106)
        self.assertIsNone(claim(self.db,now=1000))

    def test_expired_lease_reclaimed_and_stale_token_rejected(self):
        enqueue(self.db,"stage","series:4:1:2","{}")
        first=claim(self.db,now=100)
        second=claim(self.db,now=401)
        self.assertEqual(first["id"],second["id"])
        with self.assertRaises(ValueError):
            finish(self.db,first["id"],first["lease_token"],"DONE",now=402)
        finish(self.db,second["id"],second["lease_token"],"DONE",now=402)

if __name__=="__main__":
    unittest.main()
