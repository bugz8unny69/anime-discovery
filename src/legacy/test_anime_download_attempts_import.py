import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_download_attempts_import import import_download_attempts

DDL = ("CREATE TABLE download_attempts (id INTEGER PRIMARY KEY, "
       "series_id INTEGER NOT NULL, season INTEGER NOT NULL, "
       "episode INTEGER NOT NULL, torrent_hash TEXT NOT NULL UNIQUE, "
       "release_title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED', "
       "progress REAL NOT NULL DEFAULT 0, last_progress_at TEXT, "
       "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
       "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

class ArchiveTests(unittest.TestCase):
    def test_replay_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/"source.db", Path(tmp)/"target.db"
            with sqlite3.connect(source) as db:
                db.execute(DDL)
                db.execute("INSERT INTO download_attempts (series_id,season,episode,torrent_hash,release_title) VALUES (1,1,2,'hash','release')")
            with sqlite3.connect(target, isolation_level=None) as db:
                result = import_download_attempts(db, source)
                self.assertEqual(result["historical_rows"], 1)
                self.assertFalse(result["acquisition_enabled"])
                self.assertEqual(import_download_attempts(db, source)["historical_rows"], 1)
                db.execute("UPDATE legacy_download_attempts SET status='CHANGED'")
                with self.assertRaises(ValueError):
                    import_download_attempts(db, source)

if __name__ == "__main__":
    unittest.main()
