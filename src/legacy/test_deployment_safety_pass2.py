import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import deployment_safety_pass2 as m

SCHEMA='''CREATE TABLE series(id INTEGER PRIMARY KEY);CREATE TABLE episodes(id INTEGER PRIMARY KEY);CREATE TABLE download_attempts(id INTEGER PRIMARY KEY);CREATE TABLE staged_episodes(id INTEGER PRIMARY KEY);CREATE TABLE file_observations(id INTEGER PRIMARY KEY);'''
class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'fixture.db'
        c=sqlite3.connect(self.db);c.executescript(SCHEMA);c.execute('INSERT INTO series VALUES (1)');c.commit();c.close()
        self.api=Path(self.tmp.name)/'api.py'
        self.api.write_text('from fastapi import Depends\napp=None\ndef authenticate(): pass\n@app.get("/health")\ndef health():pass\n@app.post("/discover",dependencies=[Depends(authenticate)])\ndef discover():pass\n')
    def test_fixture(self):
        r=m.check_fixture(self.db)
        self.assertTrue(r['existing_rows_preserved']);self.assertEqual(r['quick_check_after'],'ok')
        self.assertEqual(len(r['added_tables']),3)
    def test_source_untouched(self):
        before=self.db.read_bytes();m.check_fixture(self.db);self.assertEqual(self.db.read_bytes(),before)
    def test_repeated(self):self.assertTrue(m.check_fixture(self.db)['migration_repeated'])
    def test_missing_fixture(self):
        with self.assertRaises(ValueError):m.check_fixture(Path(self.tmp.name)/'missing.db')
    def test_wrong_extension(self):
        p=Path(self.tmp.name)/'foo.sqlite';p.write_bytes(self.db.read_bytes())
        with self.assertRaises(ValueError):m.check_fixture(p)
    def test_production_path(self):
        with patch.object(m,'PRODUCTION_DB',str(self.db)):
            with self.assertRaises(ValueError):m.check_fixture(self.db)
    def test_hardlink(self):
        link=Path(self.tmp.name)/'link.db';link.hardlink_to(self.db)
        with patch.object(m,'PRODUCTION_DB',str(self.db)):
            with self.assertRaises(ValueError):m.check_fixture(link)
    def test_missing_table(self):
        c=sqlite3.connect(self.db);c.execute('DROP TABLE episodes');c.commit();c.close()
        with self.assertRaises(ValueError):m.check_fixture(self.db)
    def test_source_routes(self):self.assertEqual(m.audit_source(self.api)['route_count'],2)
    def test_auth_present(self):self.assertEqual(m.audit_source(self.api)['unprotected_non_health'],[])
    def test_auth_missing(self):
        self.api.write_text('@app.post("/discover")\ndef discover():pass\n')
        self.assertEqual(m.audit_source(self.api)['unprotected_non_health'],['/discover'])
    def test_no_source_execution(self):
        self.api.write_text('raise RuntimeError("executed")\n@app.get("/health")\ndef health():pass\n')
        self.assertEqual(m.audit_source(self.api)['route_count'],1)
    def test_report_not_ready(self):
        r=m.build_report(self.api,self.db)
        self.assertFalse(r['production_ready']);self.assertFalse(r['live_cancellation_enabled'])
    def test_report_blockers(self):self.assertGreaterEqual(len(m.build_report(self.api,self.db)['remaining_blockers']),5)
    def test_json_format(self):self.assertEqual(m.build_report(self.api,self.db)['format'],'anime-deployment-safety-v1')
    def test_source_readonly(self):self.assertTrue(m.check_fixture(self.db)['source_opened_read_only'])
if __name__=='__main__':unittest.main()
