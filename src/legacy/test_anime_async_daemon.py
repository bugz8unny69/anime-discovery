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

    def test_worker_finishes_job_without_local_logging_shadow(self):
        import asyncio
        from anime_async_daemon import run_workers
        db_path=Path(self.temp.name)/"worker-logging.db"
        with sqlite3.connect(db_path,isolation_level=None) as worker_db:
            enqueue(worker_db,"identify","notification:51","{}")
        stop=asyncio.Event()
        async def handler(job):
            stop.set()
            return "DONE"
        asyncio.run(run_workers(db_path,{"identify":handler},
            concurrency=1,poll_seconds=0.01,stop=stop))
        with sqlite3.connect(db_path) as worker_db:
            self.assertEqual(worker_db.execute(
                "SELECT state FROM daemon_jobs WHERE subject_key='notification:51'"
            ).fetchone()[0],"DONE")

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
