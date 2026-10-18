import os, sqlite3, tempfile, unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import trial_integration_sprint as m

SCHEMA='''
CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT NOT NULL);
CREATE TABLE download_attempts(id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT);
CREATE TABLE staged_episodes(series_id INTEGER,season INTEGER,episode INTEGER,attempt_id INTEGER,status TEXT,staged_path TEXT,imported_path TEXT,PRIMARY KEY(series_id,season,episode));
'''
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.path=str(Path(self.tmp.name)/'fixture.db')
  with sqlite3.connect(self.path) as db:
   db.executescript(SCHEMA)
   db.execute("INSERT INTO series VALUES(1,'ACQUIRING')")
   db.execute("INSERT INTO download_attempts VALUES(11,1,1,1,?,'COMPLETED')",('a'*40,))
   db.execute("INSERT INTO download_attempts VALUES(12,1,1,2,?,'DOWNLOADING')",('b'*40,))
   db.execute("INSERT INTO staged_episodes VALUES(1,1,1,11,'STAGED','/synthetic/e1.mkv',NULL)")
  with sqlite3.connect(self.path,isolation_level=None) as db:
   db.execute('PRAGMA foreign_keys=ON');m.install(db)
   db.execute("INSERT INTO trial_mapping_gate VALUES(1,'MANUAL_APPROVED',1,?, 'offline-admin')",('a'*64,))
  self.verifies=True
  app=FastAPI();app.include_router(m.make_router(db_path=self.path,decision_token='admin-secret',discovery_token='discovery-secret',verify_episode1=lambda db,sid,aid:self.verifies))
  self.client=TestClient(app)
 def request(self,action='KEEP',token='admin-secret',attempt=11):
  return self.client.post('/offline-trial/series/1/decision',json={'action':action,'episode1_attempt_id':attempt},headers={'Authorization':'Bearer '+token})
 def query(self,sql):
  with sqlite3.connect(self.path) as db:return db.execute(sql).fetchall()
 def test_decision(self):self.assertEqual(self.request().status_code,200)
 def test_discovery_token_denied(self):self.assertEqual(self.request(token='discovery-secret').status_code,401)
 def test_invalid_token_denied(self):self.assertEqual(self.request(token='wrong').status_code,401)
 def test_missing_token_denied(self):self.assertEqual(self.client.post('/offline-trial/series/1/decision',json={'action':'KEEP','episode1_attempt_id':11}).status_code,401)
 def test_invalid_action(self):self.assertEqual(self.request('APPROVE').status_code,422)
 def test_missing_attempt(self):self.assertEqual(self.request(attempt=13).status_code,409)
 def test_stale_attempt(self):self.assertEqual(self.request(attempt=12).status_code,409)
 def test_verifier_fail_closed(self):self.verifies=False;self.assertEqual(self.request().status_code,409)
 def test_duplicate(self):self.assertEqual(self.request().status_code,200);self.assertEqual(self.request().json()['result'],'unchanged')
 def test_conflicting(self):self.request();self.assertEqual(self.request('REJECT').status_code,409)
 def test_early_decision(self):self.assertEqual(self.request().status_code,200);self.assertEqual(self.query('SELECT status FROM download_attempts WHERE id=12')[0][0],'DOWNLOADING')
 def test_outbox(self):self.request();self.assertEqual(self.query('SELECT attempt_id,delete_files FROM trial_cancel_outbox'),[(12,0)])
 def test_no_cancel_for_completed(self):self.request();self.assertNotIn((11,0),self.query('SELECT attempt_id,delete_files FROM trial_cancel_outbox'))
 def test_atomic_failure(self):
  with sqlite3.connect(self.path) as db:db.execute('DROP TABLE trial_cancel_outbox')
  with self.assertRaises(sqlite3.OperationalError):self.request()
  self.assertEqual(self.query('SELECT * FROM trial_decision_gate'),[])
 def test_mapping_missing(self):
  with sqlite3.connect(self.path) as db:db.execute('DELETE FROM trial_mapping_gate')
  self.assertEqual(self.request().status_code,409)
 def test_mapping_review_required(self):
  with sqlite3.connect(self.path) as db:db.execute("UPDATE trial_mapping_gate SET state='REVIEW_REQUIRED'")
  self.assertEqual(self.request().status_code,409)
 def test_series_terminal(self):
  with sqlite3.connect(self.path) as db:db.execute("UPDATE series SET status='REJECTED'")
  self.assertEqual(self.request().status_code,409)
 def test_staged_attempt_mismatch(self):
  with sqlite3.connect(self.path) as db:db.execute('UPDATE staged_episodes SET attempt_id=12')
  self.assertEqual(self.request().status_code,409)
 def test_no_live_cancellation(self):self.assertFalse(self.request().json()['cancellation_enabled'])
 def test_migration_idempotent(self):
  with sqlite3.connect(self.path,isolation_level=None) as db:m.install(db)
 def test_migration_rollback(self):
  with sqlite3.connect(self.path,isolation_level=None) as db:
   db.execute('DROP TABLE trial_cancel_outbox');db.execute('CREATE VIEW trial_cancel_outbox AS SELECT 1 AS id')
   with self.assertRaises(sqlite3.OperationalError):m.install(db)
 def test_same_token_refused(self):
  with self.assertRaises(ValueError):m.make_router(db_path=self.path,decision_token='x',discovery_token='x',verify_episode1=lambda *a:True)
 def test_missing_db_refused(self):
  with self.assertRaises(ValueError):m.make_router(db_path=self.path+'x',decision_token='a',discovery_token='b',verify_episode1=lambda *a:True)
 def test_production_path_refused(self):
  with self.assertRaises(ValueError):m.assert_disposable(m.PRODUCTION_DB)
 def test_mapping_admin_cannot_be_blank(self):
  with sqlite3.connect(self.path) as db:
   with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE trial_mapping_gate SET admin_actor='' ")
if __name__=='__main__':unittest.main()
