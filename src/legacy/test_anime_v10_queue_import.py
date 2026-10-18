import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_v10_queue_import import import_identity_queue_v10

class V10QueueImportTests(unittest.TestCase):
    def test_import_is_idempotent_and_never_activates_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory)/"v10.db"
            dst=Path(directory)/"unified.db"
            with sqlite3.connect(src) as db:
                db.execute("""CREATE TABLE identity_queue(
                    notification_id INTEGER PRIMARY KEY,last_action TEXT NOT NULL,
                    attempts INTEGER NOT NULL,next_at REAL NOT NULL,
                    updated_at REAL NOT NULL)""")
                db.execute("INSERT INTO identity_queue VALUES (17,'RETRY',2,100.5,90.5)")
            with sqlite3.connect(dst,isolation_level=None) as db:
                first=import_identity_queue_v10(db,src)
                second=import_identity_queue_v10(db,src)
                self.assertEqual(first["imported_rows"],1)
                self.assertFalse(second["queue_activated"])
                self.assertEqual(db.execute(
                    "SELECT notification_id,attempts FROM legacy_identity_queue_v10").fetchall(),[(17,2)])
                db.execute("UPDATE legacy_identity_queue_v10 SET attempts=99")
                with self.assertRaisesRegex(ValueError,"Conflicting"):
                    import_identity_queue_v10(db,src)
                self.assertEqual(db.execute(
                    "SELECT attempts FROM legacy_identity_queue_v10").fetchone()[0],99)
            with sqlite3.connect(src) as db:
                self.assertEqual(db.execute("SELECT attempts FROM identity_queue").fetchone()[0],2)

if __name__=="__main__":
    unittest.main()
