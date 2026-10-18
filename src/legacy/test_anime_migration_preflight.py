import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_migration_preflight import preflight

class PreflightTests(unittest.TestCase):
    def test_bootstrap_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE schema_bootstrap(id INTEGER PRIMARY KEY,status TEXT)")
                db.execute("INSERT INTO schema_bootstrap VALUES(1,'PENDING_MIGRATIONS')")
            result=preflight(path)
            self.assertFalse(result["ready"])
            self.assertEqual(result["bootstrap_status"],"PENDING_MIGRATIONS")
            self.assertIn("episode_dispatch",result["missing_tables"])

    def test_missing_database_does_not_get_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"missing.db"
            with self.assertRaises(FileNotFoundError):
                preflight(path)
            self.assertFalse(path.exists())

if __name__=="__main__":
    unittest.main()
