import sqlite3
import unittest
from anime_async_daemon import claim,enqueue

class HandlerRoutingTests(unittest.TestCase):
    def test_claim_only_registered_kind(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        try:
            enqueue(db,"unsupported_download","first","{}")
            enqueue(db,"migration_preflight","second","{}")
            job=claim(db,allowed_kinds={"migration_preflight"})
            self.assertEqual(job["kind"],"migration_preflight")
            self.assertEqual(db.execute(
                "SELECT state FROM daemon_jobs WHERE kind='unsupported_download'").fetchone()[0],"READY")
            self.assertIsNone(claim(db,allowed_kinds={"migration_preflight"}))
            with self.assertRaises(ValueError):
                claim(db,allowed_kinds=set())
        finally:
            db.close()

if __name__=="__main__":
    unittest.main()
