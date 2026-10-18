"""Tests for evidence importer with missing source files."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_unified_evidence_import import import_evidence

class EvidenceImportTests(unittest.TestCase):
    def test_missing_source_does_not_modify_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with sqlite3.connect(":memory:", isolation_level=None) as db:
                db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY)")
                with self.assertRaises(FileNotFoundError):
                    import_evidence(db,Path(tmp)/"missing-verified.db",Path(tmp)/"missing-shadow.db")
                tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                self.assertEqual(tables,["notifications"])

if __name__=="__main__":
    unittest.main()
