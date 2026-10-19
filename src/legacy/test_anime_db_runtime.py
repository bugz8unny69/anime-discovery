"""Offline tests for the opt-in unified database runtime."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_db_runtime import connect, database_path, transaction


class DatabaseRuntimeTests(unittest.TestCase):
    def test_path_override(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.db"
            with patch.dict("os.environ", {"ANIME_DISCOVERY_DB_PATH": str(path)}):
                self.assertEqual(database_path(), path.resolve())

    def test_blank_override_rejected(self):
        with patch.dict("os.environ", {"ANIME_DISCOVERY_DB_PATH": " "}):
            with self.assertRaises(ValueError):
                database_path()

    def test_settings_and_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.db"
            with transaction(path) as db:
                self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                db.execute("CREATE TABLE entries (value TEXT)")
                db.execute("INSERT INTO entries VALUES ('ok')")
            db = connect(path, read_only=True)
            try:
                self.assertEqual(db.execute("SELECT value FROM entries").fetchone()[0], "ok")
            finally:
                db.close()

    def test_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.db"
            with transaction(path) as db:
                db.execute("CREATE TABLE entries (value TEXT)")
            with self.assertRaises(RuntimeError):
                with transaction(path) as db:
                    db.execute("INSERT INTO entries VALUES ('rollback')")
                    raise RuntimeError("fail")
            db = connect(path, read_only=True)
            try:
                self.assertEqual(db.execute("SELECT count(*) FROM entries").fetchone()[0], 0)
            finally:
                db.close()

    def test_readonly_missing_db_does_not_create(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                connect(path, read_only=True)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
