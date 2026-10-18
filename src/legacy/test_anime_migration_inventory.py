import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_migration_inventory import inventory

class InventoryTests(unittest.TestCase):
    def test_counts_rows_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"legacy.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE example(id INTEGER)")
                db.executemany("INSERT INTO example VALUES(?)",[(1,),(2,)])
            self.assertEqual(inventory(path)["example"],2)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM example").fetchone()[0],2)

if __name__=="__main__":
    unittest.main()
