import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from fastapi.testclient import TestClient
from trial_decision_api_rehearsal import create_app, initialize_disposable

class TrialDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'test.sqlite')
        initialize_disposable(self.path)
        self.app = create_app(self.path, decision_token='decision-secret', discovery_token='discovery-secret')
        self.client = TestClient(self.app)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO trials VALUES(1,'APPROVED',1,11,'ACQUIRING')")
            db.execute("INSERT INTO attempts VALUES(11,1,?,'COMPLETED')", ('a'*40,))
            db.execute("INSERT INTO attempts VALUES(12,1,?,'DOWNLOADING')", ('b'*40,))
            db.commit()
    def post(self, action='KEEP', attempt_id=11, token='decision-secret'):
        return self.client.post('/trial-rehearsal/series/1/decision', json={'action':action,'attempt_id':attempt_id}, headers={'Authorization':'Bearer '+token})
    def change(self, query):
        with closing(sqlite3.connect(self.path)) as db: db.execute(query); db.commit()
    def count(self, table):
        with closing(sqlite3.connect(self.path)) as db: return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def test_keep(self): self.assertEqual(self.post().status_code,200)
    def test_reject(self): self.assertEqual(self.post('REJECT').status_code,200)
    def test_no_token(self): self.assertEqual(self.client.post('/trial-rehearsal/series/1/decision',json={'action':'KEEP','attempt_id':11}).status_code,401)
    def test_discovery_token_denied(self): self.assertEqual(self.post(token='discovery-secret').status_code,401)
    def test_wrong_token(self): self.assertEqual(self.post(token='wrong').status_code,401)
    def test_unknown_action(self): self.assertEqual(self.post('APPROVED').status_code,422)
    def test_stale_attempt(self): self.assertEqual(self.post(attempt_id=12).status_code,409)
    def test_unverified(self):
        self.change('UPDATE trials SET episode1_verified=0');self.assertEqual(self.post().status_code,409)
    def test_unapproved_mapping(self):
        self.change("UPDATE trials SET mapping_state='PENDING'");self.assertEqual(self.post().status_code,409)
    def test_not_acquiring(self):
        self.change("UPDATE trials SET state='DECIDED'");self.assertEqual(self.post().status_code,409)
    def test_attempt_not_complete(self):
        self.change("UPDATE attempts SET status='DOWNLOADING' WHERE id=11");self.assertEqual(self.post().status_code,409)
    def test_unknown_series(self):
        self.assertEqual(self.client.post('/trial-rehearsal/series/99/decision',json={'action':'KEEP','attempt_id':11},headers={'Authorization':'Bearer decision-secret'}).status_code,404)
    def test_idempotent(self):
        self.post();self.assertEqual(self.post().json()['result'],'unchanged')
    def test_conflicting(self):
        self.post();self.assertEqual(self.post('REJECT').status_code,409)
    def test_outbox(self):
        self.post();self.assertEqual(self.count('cancellation_outbox'),1)
    def test_no_outbox_on_failure(self):
        self.post(attempt_id=12);self.assertEqual(self.count('cancellation_outbox'),0)
    def test_decision_atomic(self):
        self.post();self.assertEqual(self.count('decisions'),1)
    def test_distinct_tokens(self):
        with self.assertRaises(ValueError):create_app(self.path,decision_token='same',discovery_token='same')
    def test_no_production_path(self):
        with self.assertRaises(ValueError):create_app('/var/lib/anime-discovery/controller.db',decision_token='a',discovery_token='b')
    def test_no_existing_initialize(self):
        with self.assertRaises(ValueError):initialize_disposable(self.path)

if __name__ == '__main__':unittest.main()
