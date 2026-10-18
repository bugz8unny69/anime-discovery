import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_migration_row_audit import compare_operational_table

class RowAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src=Path(self.tmp.name)/"source.db"
        self.dst=Path(self.tmp.name)/"target.db"
        for path in (self.src,self.dst):
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE queue_history(id INTEGER, payload BLOB)")
                db.executemany("INSERT INTO queue_history VALUES (?,?)",
                               [(1,b"one"),(1,b"one"),(2,b"two")])
    def test_equal_multisets(self):
        result=compare_operational_table(self.src,self.dst,"queue_history")
        self.assertTrue(result["equal"])
        self.assertEqual(result["source_rows"],3)
    def test_same_count_different_rows(self):
        with sqlite3.connect(self.dst) as db:
            db.execute("UPDATE queue_history SET payload=? WHERE id=2",(b"changed",))
        result=compare_operational_table(self.src,self.dst,"queue_history")
        self.assertFalse(result["equal"])
        self.assertEqual(result["source_rows"],result["target_rows"])
        self.assertEqual(result["missing_rows"],1)
    def test_missing_table(self):
        with sqlite3.connect(self.dst) as db:
            db.execute("DROP TABLE queue_history")
        self.assertFalse(compare_operational_table(self.src,self.dst,"queue_history")["equal"])
    def test_schema_mismatch(self):
        with sqlite3.connect(self.dst) as db:
            db.execute("ALTER TABLE queue_history ADD COLUMN state TEXT")
        self.assertEqual(compare_operational_table(self.src,self.dst,"queue_history")["reason"],
                         "Schema differs")

if __name__=="__main__":
    unittest.main()
