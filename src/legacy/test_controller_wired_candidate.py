import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from controller_wired_candidate import create_app
from live_boundary_patch import FileFingerprint

SCHEMA = '''
CREATE TABLE series(id INTEGER PRIMARY KEY,status TEXT NOT NULL);
CREATE TABLE download_attempts(id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT);
CREATE TABLE staged_episodes(series_id INTEGER,season INTEGER,episode INTEGER,attempt_id INTEGER,status TEXT,staged_path TEXT,imported_path TEXT,PRIMARY KEY(series_id,season,episode));
'''

class WiredTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.staging = root/'staging'; self.staging.mkdir()
        self.library = root/'library'; self.library.mkdir()
        self.db = root/'fixture.db'; self.file = self.staging/'e1.mkv'; self.file.write_bytes(b'test media')
        with sqlite3.connect(self.db) as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO series VALUES(1,'ACQUIRING')")
            db.execute("INSERT INTO download_attempts VALUES(11,1,1,1,?,'COMPLETED')", ('a'*40,))
            db.execute("INSERT INTO download_attempts VALUES(12,1,1,2,?,'DOWNLOADING')", ('b'*40,))
            db.execute("INSERT INTO staged_episodes VALUES(1,1,1,11,'STAGED',?,NULL)", (str(self.file),))
        self.app = create_app(candidate_path=Path(__file__).parent/'api.candidate.py', disposable_db=self.db,
                              decision_token='decision-secret', discovery_token='discovery-secret',
                              staging_root=self.staging, library_root=self.library)
        self.client = TestClient(self.app)
    def request(self, token='decision-secret', action='KEEP'):
        return self.client.post('/offline-trial/series/1/decision', headers={'Authorization':'Bearer '+token},
                                json={'action':action,'episode1_attempt_id':11})
    def approve_fixture(self):
        # Synthetic approval is *only* for a disposable test DB; not a trusted provider.
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO trial_mapping_gate VALUES(1,'MANUAL_APPROVED',1,?,'fixture')", ('a'*64,))
    def test_health(self): self.assertEqual(self.client.get('/health').status_code, 200)
    def test_discovery_cannot_decide(self): self.assertEqual(self.request('discovery-secret').status_code, 401)
    def test_decision_cannot_discover(self): self.assertEqual(self.client.get('/series',headers={'Authorization':'Bearer decision-secret'}).status_code,401)
    def test_missing_mapping_fails(self): self.assertEqual(self.request().status_code,409)
    def test_unverified_file_fails(self):
        self.approve_fixture(); self.assertEqual(self.request().status_code,409)
    def test_no_outbox_on_failed_verification(self):
        self.approve_fixture(); self.request()
        with sqlite3.connect(self.db) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM trial_cancel_outbox').fetchone()[0],0)
    def test_legacy_review_blocked(self):
        self.assertEqual(self.client.post('/series/1/review',headers={'Authorization':'Bearer discovery-secret'},json={'status':'APPROVED'}).status_code,403)
    def test_fake_verification_cannot_be_supplied_in_request(self):
        self.approve_fixture()
        r=self.client.post('/offline-trial/series/1/decision',headers={'Authorization':'Bearer decision-secret'},json={'action':'KEEP','episode1_attempt_id':11,'verified':True})
        self.assertEqual(r.status_code,409)
    def test_production_db_rejected(self):
        with self.assertRaises(ValueError): create_app(candidate_path=Path(__file__).parent/'api.candidate.py',disposable_db='/var/lib/anime-discovery/controller.db',decision_token='a',discovery_token='b',staging_root=self.staging,library_root=self.library)
    def test_matching_credentials_rejected(self):
        with self.assertRaises(ValueError): create_app(candidate_path=Path(__file__).parent/'api.candidate.py',disposable_db=self.db,decision_token='same',discovery_token='same',staging_root=self.staging,library_root=self.library)
    def test_real_verifier_not_mock_boolean(self):
        self.approve_fixture()
        with patch('controller_wired_candidate.verified_episode1_snapshot', return_value=None) as verify:
            self.assertEqual(self.request().status_code,409)
            verify.assert_called_once()
    def test_replaced_file_is_rejected(self):
        self.approve_fixture()
        from live_boundary_patch import fingerprint_regular_file
        fp = fingerprint_regular_file(self.file, self.staging)
        try:
            self.file.unlink(); self.file.write_bytes(b'test media')
            with patch('controller_wired_candidate.verified_episode1_snapshot',return_value=fp):
                self.assertEqual(self.request().status_code,409)
        finally: fp.close()
    def test_no_external_cancellation(self):
        self.approve_fixture(); self.request()
        with sqlite3.connect(self.db) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM trial_cancel_outbox').fetchone()[0],0)

if __name__=='__main__': unittest.main()
