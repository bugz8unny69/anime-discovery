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

    def test_conflicting_target_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            target=Path(directory)/"target.db"
            for path in (source,target):
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE legacy_queue(id INTEGER,state TEXT)")
            with sqlite3.connect(source) as db:
                db.execute("INSERT INTO legacy_queue VALUES(1,'PENDING')")
            with sqlite3.connect(target) as db:
                db.execute("INSERT INTO legacy_queue VALUES(1,'REJECTED')")
            with sqlite3.connect(target,isolation_level=None) as db:
                with self.assertRaisesRegex(ValueError,"Conflicting"):
                    import_operational_tables(db,source,["legacy_queue"])
                self.assertEqual(db.execute("SELECT state FROM legacy_queue").fetchone()[0],
                                 "REJECTED")

    def test_schema_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            target=Path(directory)/"target.db"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE legacy_queue(id INTEGER)")
            with sqlite3.connect(target) as db:
                db.execute("CREATE TABLE legacy_queue(id INTEGER,state TEXT)")
            with sqlite3.connect(target,isolation_level=None) as db:
                with self.assertRaisesRegex(ValueError,"Schema mismatch"):
                    import_operational_tables(db,source,["legacy_queue"])

if __name__=="__main__":
    unittest.main()
