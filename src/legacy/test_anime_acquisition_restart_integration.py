"""Offline integration tests with persistent SQLite and simulated restarts."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_async_daemon import ensure_schema, claim, finish
from anime_external_actions import reserve
from anime_qb_submission import submit_once

class FakeQB:
    present=False
    adds=0
    def contains_hash(self, key):
        return self.present
    def add_magnet(self, magnet):
        self.adds+=1
        self.present=True

class AcquisitionRestartTests(unittest.TestCase):
    def test_expired_lease_is_fenced_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"state.db"
            with sqlite3.connect(path,isolation_level=None) as db:
                ensure_schema(db)
                db.execute("INSERT INTO daemon_jobs(kind,subject_key,payload_json,state) VALUES ('claimed_acquisition','7','{}','READY')")
                old=claim(db,now=100,lease_seconds=30,allowed_kinds=["claimed_acquisition"])
            with sqlite3.connect(path,isolation_level=None) as db:
                new=claim(db,now=131,lease_seconds=300,allowed_kinds=["claimed_acquisition"])
                self.assertNotEqual(old["lease_token"],new["lease_token"])
                with self.assertRaisesRegex(ValueError,"Stale"):
                    finish(db,old["id"],old["lease_token"],"DONE",now=132)
                finish(db,new["id"],new["lease_token"],"DEFERRED",now=132)
                self.assertEqual(db.execute("SELECT state FROM daemon_jobs").fetchone()[0],"DEFERRED")

    def test_reserved_submission_reconciles_across_restart(self):
        import hashlib
        h="a"*40
        magnet="magnet:?xt=urn:btih:"+h
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"state.db"
            with sqlite3.connect(path,isolation_level=None) as db:
                reserve(db,"qbittorrent_submit",h,hashlib.sha256(magnet.encode()).hexdigest())
            qb=FakeQB()
            with sqlite3.connect(path,isolation_level=None) as db:
                self.assertIsNone(submit_once(db,h,magnet,qb))
                self.assertEqual(qb.adds,0)
            qb.present=True
            with sqlite3.connect(path,isolation_level=None) as db:
                self.assertEqual(submit_once(db,h,magnet,qb),h)
                self.assertEqual(qb.adds,0)
                self.assertEqual(db.execute("SELECT state FROM external_actions").fetchone()[0],"CONFIRMED")

if __name__=="__main__":
    unittest.main()
