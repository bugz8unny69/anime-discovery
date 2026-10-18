import sqlite3
import unittest
from anime_rejection_store import ensure_schema, is_blocked, reject, reset_rejection

class RejectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE series(id INTEGER PRIMARY KEY)")
        self.db.execute("INSERT INTO series VALUES (1)")
        ensure_schema(self.db)

    def test_rejection_survives_unrelated_history_clear(self):
        self.db.execute("CREATE TABLE processing_history(series_id INTEGER)")
        self.db.execute("INSERT INTO processing_history VALUES (1)")
        reject(self.db, 1, "user rejected")
        self.db.execute("DELETE FROM processing_history WHERE series_id=1")
        self.assertTrue(is_blocked(self.db, 1))
        with self.assertRaises(PermissionError):
            reset_rejection(self.db, 1)
        self.assertTrue(is_blocked(self.db, 1))
        self.assertTrue(reset_rejection(self.db, 1, confirmed=True))
        self.assertFalse(is_blocked(self.db, 1))
        self.assertEqual(self.db.execute("SELECT action FROM series_admin_audit ORDER BY id").fetchall(), [("REJECT",), ("RESET_REJECTION",)])

    def test_unknown_series_fails(self):
        with self.assertRaises(ValueError):
            reject(self.db, 999, "reject")
        with self.assertRaises(ValueError):
            reset_rejection(self.db, 999, confirmed=True)

    def test_missing_table_fails_closed(self):
        self.db.execute("DROP TABLE series_rejection_blocks")
        with self.assertRaises(sqlite3.OperationalError):
            is_blocked(self.db, 1)

if __name__ == "__main__":
    unittest.main()
