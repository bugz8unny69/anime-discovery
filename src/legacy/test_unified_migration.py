"""Synthetic-only tests: no production databases touched."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unified_migration import merge

class MergeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        self.controller=root/"controller.db"
        self.inbox=root/"inbox.db"
        self.output=root/"merged.db"
        with sqlite3.connect(self.controller) as db:
            db.executescript('CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,title TEXT,status TEXT); CREATE TABLE episodes(series_id INTEGER,season INTEGER,episode INTEGER,status TEXT); INSERT INTO series VALUES (1,"test","TEST-001","Fixture","DISCOVERED"); INSERT INTO series VALUES (2,"tvdb","real","Real","DISCOVERED");')
        with sqlite3.connect(self.inbox) as db:
            db.executescript('CREATE TABLE notifications(id INTEGER PRIMARY KEY,source TEXT,release_name TEXT,source_guid TEXT,info_hash TEXT,received_at INTEGER,status TEXT); INSERT INTO notifications VALUES (1,"nyaa","Release","guid","abcdef",100,"UNTRUSTED");')

    def test_preserves_notification_and_quarantines_fixture(self):
        self.assertEqual(merge(self.controller,self.inbox,self.output),{"series":2,"notifications":1,"quarantined":1})
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute("SELECT status FROM notifications").fetchone()[0],"UNTRUSTED")
            self.assertEqual(db.execute("SELECT series_id FROM migration_quarantined_series").fetchall(),[(1,)])
        with sqlite3.connect(self.controller) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM series").fetchone()[0],2)

    def test_refuses_overwrite(self):
        self.output.touch()
        with self.assertRaises(ValueError):
            merge(self.controller,self.inbox,self.output)

    def test_bad_schema_removes_partial_output(self):
        with sqlite3.connect(self.inbox) as db:
            db.execute("DROP TABLE notifications")
        with self.assertRaises(ValueError):
            merge(self.controller,self.inbox,self.output)
        self.assertFalse(self.output.exists())

if __name__=="__main__":
    unittest.main()
