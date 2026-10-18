import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from controller_integrated_offline import create_offline_app, load_candidate

SCHEMA = '''
CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT NOT NULL);
CREATE TABLE download_attempts(id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT);
CREATE TABLE staged_episodes(series_id INTEGER,season INTEGER,episode INTEGER,attempt_id INTEGER,status TEXT,staged_path TEXT,imported_path TEXT,PRIMARY KEY(series_id,season,episode));
'''
SOURCE = str(Path(__file__).parent / 'api.candidate.py')

class OfflineIntegratedTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name);self.staging=root/'staging';self.library=root/'library';self.staging.mkdir();self.library.mkdir()
  self.db=root/'fixture.db'
  with sqlite3.connect(self.db) as db:
   db.executescript(SCHEMA)
   db.execute("INSERT INTO series VALUES(1,'ACQUIRING')")
   db.execute("INSERT INTO download_attempts VALUES(11,1,1,1,?,'COMPLETED')",('a'*40,))
   db.execute("INSERT INTO download_attempts VALUES(12,1,1,2,?,'DOWNLOADING')",('b'*40,))
   db.execute("INSERT INTO staged_episodes VALUES(1,1,1,11,'STAGED',?,NULL)",(str(self.staging/'e1.mkv'),))
  self.app=create_offline_app(candidate_path=SOURCE,disposable_db=str(self.db),decision_token='admin-token',discovery_token='discovery-token',staging_root=self.staging,library_root=self.library)
  self.client=TestClient(self.app)
 def request(self,token='admin-token'):
  return self.client.post('/offline-trial/series/1/decision',headers={'Authorization':'Bearer '+token},json={'action':'KEEP','episode1_attempt_id':11})
 def test_health(self):self.assertEqual(self.client.get('/health').status_code,200)
 def test_admin_auth(self):self.assertEqual(self.request(token='discovery-token').status_code,401)
 def test_no_token(self):self.assertEqual(self.client.post('/offline-trial/series/1/decision',json={'action':'KEEP','episode1_attempt_id':11}).status_code,401)
 def test_missing_mapping(self):self.assertEqual(self.request().status_code,409)
 def test_unverified_media_fail_closed(self):
  with sqlite3.connect(self.db) as db:db.execute("INSERT INTO trial_mapping_gate VALUES(1,'MANUAL_APPROVED',1,?,'offline-admin')",('a'*64,))
  self.assertEqual(self.request().status_code,409)
 def test_discovery_endpoint_not_admin(self):
  r=self.client.post('/series/1/review',headers={'Authorization':'Bearer discovery-token'},json={'status':'APPROVED'})
  self.assertIn(r.status_code,(403,409,422))
 def test_invalid_discovery_token(self):
  self.assertEqual(self.client.get('/series',headers={'Authorization':'Bearer admin-token'}).status_code,401)
 def test_production_db_refused(self):
  with self.assertRaises(ValueError):create_offline_app(candidate_path=SOURCE,disposable_db='/var/lib/anime-discovery/controller.db',decision_token='a',discovery_token='b',staging_root=self.staging,library_root=self.library)
 def test_production_media_refused(self):
  with self.assertRaises(ValueError):create_offline_app(candidate_path=SOURCE,disposable_db=self.db,decision_token='a',discovery_token='b',staging_root='/mnt/media/Torrents/anime-trial',library_root=self.library)
 def test_same_tokens_refused(self):
  with self.assertRaises(ValueError):create_offline_app(candidate_path=SOURCE,disposable_db=self.db,decision_token='a',discovery_token='a',staging_root=self.staging,library_root=self.library)
 def test_original_source_refused(self):
  with self.assertRaises(ValueError):load_candidate('/opt/anime-discovery/api.py')
 def test_migration_idempotent(self):
  create_offline_app(candidate_path=SOURCE,disposable_db=self.db,decision_token='a',discovery_token='b',staging_root=self.staging,library_root=self.library)
 def test_no_outbox_on_failure(self):
  self.request()
  with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM trial_cancel_outbox').fetchone()[0],0)

if __name__=='__main__':unittest.main()
