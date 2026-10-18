"""Offline integration of fresh admin database, real approval gate and enqueue."""
import asyncio
import importlib.util
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_acquisition_handler import make_acquisition_handler
from test_anime_acquisition_end_to_end import FakeQB

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

    def test_offline_handler_completes_on_fresh_schema(self):
        download = Path(self.tmp.name) / "downloads"
        trial = Path(self.tmp.name) / "trial"
        download.mkdir()
        trial.mkdir()
        source = download / "episode.mkv"
        source.write_bytes(b"offline test media bytes" * 4096)
        self.enqueue()
        job = claim(self.db, allowed_kinds=["claimed_acquisition"])
        self.assertIsNotNone(job)
        qb = FakeQB()
        handler = make_acquisition_handler(
            self.path, lambda: qb, download_root=download, trial_root=trial)
        with (patch("anime_media_flow.confirmed_jp_en", return_value=True),
              patch("anime_source_retention.confirmed_jp_en", return_value=True)):
            outcome = asyncio.run(handler(job))
        self.assertEqual(outcome, "DONE")
        finish(self.db, job["id"], job["lease_token"], outcome)
        self.assertEqual(self.db.execute(
            "SELECT state FROM episode_dispatch").fetchone()[0], "DONE")
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_jobs").fetchone()[0], "DONE")
        staged = Path(self.db.execute(
            "SELECT staged_path FROM torrent_recovery_records").fetchone()[0])
        self.assertTrue(staged.is_file())
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),
                         hashlib.sha256(staged.read_bytes()).digest())
        self.assertTrue(source.is_file())
        self.assertEqual(qb.adds, 1)

    def test_reclaimed_lease_rejects_stale_worker(self):
        self.enqueue()
        first = claim(self.db, now=100, lease_seconds=30,
                      allowed_kinds=["claimed_acquisition"])
        self.assertIsNotNone(first)
        self.assertIsNone(claim(self.db, now=110, lease_seconds=30,
                                allowed_kinds=["claimed_acquisition"]))
        second = claim(self.db, now=131, lease_seconds=30,
                       allowed_kinds=["claimed_acquisition"])
        self.assertEqual(second["id"], first["id"])
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        with self.assertRaises(ValueError):
            finish(self.db, first["id"], first["lease_token"], "DONE", now=132)
        with self.assertRaises(ValueError):
            renew(self.db, first["id"], first["lease_token"], now=132)
        finish(self.db, second["id"], second["lease_token"], "NEEDS_REVIEW", now=132)
        self.assertEqual(self.db.execute(
            "SELECT state,attempts FROM daemon_jobs").fetchone(), ("NEEDS_REVIEW", 2))

    def test_recovery_audit_is_read_only(self):
        self.db.execute("UPDATE episode_dispatch SET attempts=3,updated_at=10")
        rows = stale_claims(self.db, now=4000, older_than_seconds=60)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempts"], 3)
        self.assertEqual(self.db.execute(
            "SELECT state FROM episode_dispatch").fetchone()[0], "CLAIMED")

    def test_unverified_episode_cannot_enqueue(self):
        self.db.execute("UPDATE episode_verification_v16 SET verified=0 WHERE notification_id=7")
        with self.assertRaises(ValueError):
            self.enqueue()
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)

    def test_fresh_schema_has_no_migration_quarantine_table(self):
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='migration_quarantined_series'").fetchone())
        self.assertIsNotNone(self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='series_quarantine'").fetchone())
        self.assertTrue(self.enqueue())

    def test_canonical_quarantine_blocks_acquisition(self):
        self.db.execute(
            "INSERT INTO series_quarantine(series_id,reason,quarantined_at) "
            "VALUES (4,'identity conflict',0)")
        with self.assertRaises(ValueError):
            self.enqueue()
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)

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
