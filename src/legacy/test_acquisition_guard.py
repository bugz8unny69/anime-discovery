import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from build_acquisition_guard import build
from controller_wired_candidate import create_app

class AcquisitionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        p=Path(self.temp.name); self.staging=p/'staging';self.staging.mkdir();self.library=p/'library';self.library.mkdir()
        self.db=p/'fixture.db'
        with sqlite3.connect(self.db) as db:
            db.executescript('''CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT NOT NULL,initial_search_complete INTEGER DEFAULT 0);
            CREATE TABLE episodes(series_id INTEGER,season INTEGER,episode INTEGER,status TEXT DEFAULT 'RESERVED',PRIMARY KEY(series_id,season,episode));
            CREATE TABLE download_attempts(id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT,progress REAL DEFAULT 0);
            CREATE TABLE staged_episodes(series_id INTEGER,season INTEGER,episode INTEGER,attempt_id INTEGER,status TEXT,staged_path TEXT,imported_path TEXT,PRIMARY KEY(series_id,season,episode));
            INSERT INTO series(id,status) VALUES(1,'ACQUIRING');
            INSERT INTO episodes(series_id,season,episode) VALUES(1,1,1);
            INSERT INTO download_attempts VALUES(11,1,1,1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','DOWNLOADING',0.1);
            ''')
        source=Path(__file__).with_name('api.candidate.py'); dest=p/'api.guarded.candidate.py'
        build(source,dest)
        self.app=create_app(candidate_path=dest,disposable_db=self.db,decision_token='admin-token',discovery_token='discovery-token',staging_root=self.staging,library_root=self.library)
        self.client=TestClient(self.app);self.headers={'Authorization':'Bearer discovery-token'}
    def decision(self):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO trial_decision_gate(series_id,action,episode1_attempt_id,mapping_revision) VALUES(1,'KEEP',11,1)")
    def post(self,path,body=None):return self.client.post(path,headers=self.headers,json=body)
    def test_reserve_before_decision_not_blocked_by_guard(self):
        self.assertEqual(self.post('/series/1/reserve',{'season':1,'episode':2}).status_code,200)
    def test_reserve_after_decision(self):
        self.decision();self.assertEqual(self.post('/series/1/reserve',{'season':1,'episode':2}).status_code,409)
    def test_register_attempt_after_decision(self):
        self.decision();self.assertEqual(self.post('/series/1/attempts',{'season':1,'episode':1,'torrent_hash':'b'*40,'release_title':'test'}).status_code,409)
    def test_update_attempt_after_decision(self):
        self.decision();self.assertEqual(self.post('/attempts/11/update',{'status':'STALLED','progress':0.1}).status_code,409)
    def test_search_complete_after_decision(self):
        self.decision();self.assertEqual(self.post('/series/1/search-complete').status_code,409)
    def test_episode_result_after_decision(self):
        self.decision();self.assertEqual(self.post('/series/1/episode-result',{'season':1,'episode':1,'status':'DOWNLOADED'}).status_code,409)
    def test_retry_after_decision(self):
        self.decision();self.assertEqual(self.post('/series/1/episodes/1/1/retry').status_code,409)
    def test_no_episode_created_after_decision(self):
        self.decision();self.post('/series/1/reserve',{'season':1,'episode':2})
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes').fetchone()[0],1)
    def test_no_attempt_update_after_decision(self):
        self.decision();self.post('/attempts/11/update',{'status':'STALLED','progress':0.1})
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT status FROM download_attempts WHERE id=11').fetchone()[0],'DOWNLOADING')
    def test_generator_rejects_in_place(self):
        source=Path(__file__).with_name('api.candidate.py')
        with self.assertRaises(ValueError):build(source,source)
    def test_generator_rejects_double_patch(self):
        with self.assertRaises(ValueError):build(Path(self.temp.name)/'api.guarded.candidate.py',Path(self.temp.name)/'again.py')
    def test_legacy_review_still_restricted(self):
        self.assertEqual(self.post('/series/1/review',{'status':'APPROVED'}).status_code,403)

if __name__=='__main__':unittest.main()
