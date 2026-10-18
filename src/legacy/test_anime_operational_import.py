import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_operational_import import import_operational_tables

class OperationalImportTests(unittest.TestCase):
    def test_repeat_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            target=Path(directory)/"target.db"
            for path in (source,target):
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE legacy_queue(id INTEGER,state TEXT)")
            with sqlite3.connect(source) as db:
                db.execute("INSERT INTO legacy_queue VALUES(1,'PENDING')")
            with sqlite3.connect(target,isolation_level=None) as db:
                import_operational_tables(db,source,["legacy_queue"])
                import_operational_tables(db,source,["legacy_queue"])
                self.assertEqual(db.execute("SELECT count(*) FROM legacy_queue").fetchone()[0],1)

if __name__=="__main__":
    unittest.main()
