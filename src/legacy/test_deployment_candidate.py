import sqlite3
import tempfile
import unittest
from pathlib import Path
from deployment_candidate import audit, snapshot_disposable, cancellation_plan
from trial_integration_sprint import install
from qb_inventory_adapter import InventoryItem

class DeploymentCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'fixture.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT);
            CREATE TABLE episodes(series_id INTEGER,season INTEGER,episode INTEGER);
            CREATE TABLE download_attempts(id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT);
            CREATE TABLE staged_episodes(series_id INTEGER,season INTEGER,episode INTEGER);
            CREATE TABLE file_observations(series_id INTEGER,season INTEGER,episode INTEGER);''')
            db.execute("INSERT INTO series VALUES(1,'ACQUIRING')")
            db.execute("INSERT INTO download_attempts VALUES(3,1,1,2,?,'DOWNLOADING')",('a'*40,))
        with sqlite3.connect(self.path,isolation_level=None) as db:
            db.execute('PRAGMA foreign_keys=ON')
            install(db)
    def seed(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO trial_decision_gate(series_id,action,episode1_attempt_id,mapping_revision) VALUES(1,'KEEP',3,1)")
            db.execute("INSERT INTO trial_cancel_outbox(series_id,attempt_id,torrent_hash) VALUES(1,3,?)",('a'*40,))
    def test_audit(self): self.assertTrue(audit(self.path)['ready_for_offline_rehearsal'])
    def test_never_production_ready(self): self.assertFalse(audit(self.path)['ready_for_production'])
    def test_snapshot(self):
        dest=Path(self.tmp.name)/'snapshot.db';snapshot_disposable(self.path,dest)
        self.assertTrue(audit(dest)['ready_for_offline_rehearsal'])
    def test_snapshot_no_overwrite(self):
        with self.assertRaises(ValueError):snapshot_disposable(self.path,self.path)
    def test_snapshot_existing(self):
        dest=Path(self.tmp.name)/'existing.db';dest.touch()
        with self.assertRaises(ValueError):snapshot_disposable(self.path,dest)
    def test_no_jobs(self):self.assertEqual(cancellation_plan(self.path,[]),[])
    def test_matching_job(self):
        self.seed();out=cancellation_plan(self.path,[InventoryItem('a'*40,'downloading','test')]);self.assertEqual(out[0]['outcome'],'WOULD_REMOVE_WITH_DELETE_FILES_FALSE')
    def test_missing_inventory_blocked(self):
        self.seed();self.assertEqual(cancellation_plan(self.path,[])[0]['outcome'],'BLOCKED')
    def test_duplicate_inventory_blocked(self):
        self.seed();i=InventoryItem('a'*40,'downloading','test');self.assertEqual(cancellation_plan(self.path,[i,i])[0]['outcome'],'BLOCKED')
    def test_changed_attempt_hash_blocked(self):
        self.seed()
        with sqlite3.connect(self.path) as db:db.execute('UPDATE download_attempts SET torrent_hash=? WHERE id=3',('b'*40,))
        self.assertEqual(cancellation_plan(self.path,[InventoryItem('a'*40,'downloading','test')])[0]['outcome'],'BLOCKED')
    def test_terminal_attempt_blocked(self):
        self.seed()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE download_attempts SET status='COMPLETED' WHERE id=3")
        self.assertEqual(cancellation_plan(self.path,[InventoryItem('a'*40,'downloading','test')])[0]['outcome'],'BLOCKED')
    def test_delete_files_guard(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE trial_cancel_outbox SET delete_files=1')
    def test_invalid_inventory_type(self):
        with self.assertRaises(ValueError):cancellation_plan(self.path,[{'hash':'a'*40}])
    def test_nonexistent_db(self):
        with self.assertRaises(ValueError):audit(Path(self.tmp.name)/'missing.db')
    def test_read_only_audit(self):
        before=self.path.read_bytes();audit(self.path);self.assertEqual(before,self.path.read_bytes())

if __name__=='__main__':unittest.main()
