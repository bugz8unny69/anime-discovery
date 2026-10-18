import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize

class FreshDatabaseTests(unittest.TestCase):
    def test_fresh_empty_database_and_no_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fresh.db"
            result = initialize(path)
            self.assertEqual(result["schema_version"], 1)
            self.assertFalse(result["acquisition_enabled"])
            self.assertFalse(result["workers_started"])
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT version FROM schema_version").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM notifications").fetchone()[0], 0)
                db.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO episodes(series_id,season,episode) VALUES (999,1,1)")
            with self.assertRaises(FileExistsError):
                initialize(path)
    def test_identity_and_dispatch_start_empty_and_reject_orphans(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fresh.db"
            initialize(path)
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA foreign_keys=ON")
                for table in ("verified_series_identity", "episode_verification_v16",
                              "episode_approval_queue", "episode_dispatch",
                              "series_rejection_blocks", "migration_quarantined_series"):
                    self.assertEqual(db.execute("SELECT count(*) FROM "+table).fetchone()[0],0)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("""INSERT INTO episode_dispatch
                        (notification_id,series_id,season,episode) VALUES (5,7,1,1)""")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_recovery_and_idempotency_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fresh.db"
            initialize(path)
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA foreign_keys=ON")
                for table in ("external_actions", "verified_series_cache",
                              "torrent_recovery_records"):
                    self.assertEqual(db.execute("SELECT count(*) FROM "+table).fetchone()[0], 0)
                columns = {row[1] for row in db.execute("PRAGMA table_info(episode_dispatch)")}
                self.assertIn("attempts", columns)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("""INSERT INTO torrent_recovery_records
                        (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
                        VALUES (999,'abc','magnet:?','/tmp/staged','abc',0)""")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_does_not_overwrite_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.db"
            path.write_bytes(b"do not overwrite")
            with self.assertRaises(FileExistsError):
                initialize(path)
            self.assertEqual(path.read_bytes(), b"do not overwrite")
    def test_rejects_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "fresh.db"
            with self.assertRaises(ValueError):
                initialize(path)
            self.assertFalse(path.exists())
if __name__ == "__main__":
    unittest.main()
