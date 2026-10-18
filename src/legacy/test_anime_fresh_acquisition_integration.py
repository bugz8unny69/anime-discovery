"""Offline integration of fresh admin database, real approval gate and enqueue."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_acquisition_enqueue import enqueue_claimed_acquisition
from anime_async_daemon import claim, finish, renew
from anime_dispatch_recovery_audit import stale_claims

spec = importlib.util.spec_from_file_location(
    "anime_admin_integration", Path(__file__).with_name("anime-discovery-admin.py"))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)

HASH = "a" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


class FreshAcquisitionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "anime.db"
        admin.new_database(self.path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute(
            "INSERT INTO series(id,source,external_id,title) VALUES (4,'tvdb','123','Example')")
        self.db.execute(
            """INSERT INTO notifications(id,source,release_name,source_guid,info_hash,received_at)
               VALUES (7,'autobrr','Example S01E01','guid-7',?,0)""", (HASH,))
        self.db.execute(
            """INSERT INTO verified_series_identity
               (notification_id,anidb_id,tvdb_id,mapping_source,decision,evidence_json,evidence_sha256)
               VALUES (7,'456','123','verified','VERIFIED','{}','evidence')""")
        self.db.execute(
            """INSERT INTO episode_verification_v16
               (notification_id,evaluated_at,decision,verified,evidence_json)
               VALUES (7,0,'VERIFIED',1,'{}')""")
        self.db.execute(
            """INSERT INTO episode_approval_queue(notification_id,decision,season,episode)
               VALUES (7,'AUTO_APPROVED',1,1)""")
        self.db.execute(
            """INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state)
               VALUES (7,4,1,1,'CLAIMED')""")

    def enqueue(self):
        return enqueue_claimed_acquisition(
            self.db, 7, infohash=HASH, magnet_uri=MAGNET, title="Example", tvdb_id=123)

    def test_real_approval_enqueue_is_idempotent_and_offline(self):
        self.assertTrue(self.enqueue())
        self.assertFalse(self.enqueue())
        self.assertEqual(self.db.execute(
            "SELECT kind,state FROM daemon_jobs").fetchall(),
            [("claimed_acquisition", "READY")])
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM external_actions").fetchone()[0], 0)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM torrent_recovery_records").fetchone()[0], 0)

    def test_unverified_episode_cannot_enqueue(self):
        self.db.execute("UPDATE episode_verification_v16 SET verified=0 WHERE notification_id=7")
        with self.assertRaises(ValueError):
            self.enqueue()
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)

    def test_rejected_series_cannot_enqueue(self):
        self.db.execute("UPDATE series SET status='REJECTED' WHERE id=4")
        with self.assertRaises(ValueError):
            self.enqueue()
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)

    def test_mismatched_episode_cannot_enqueue(self):
        self.db.execute("UPDATE episode_dispatch SET episode=2 WHERE notification_id=7")
        with self.assertRaises(ValueError):
            self.enqueue()
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
