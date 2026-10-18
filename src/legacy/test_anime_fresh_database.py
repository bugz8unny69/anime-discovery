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
