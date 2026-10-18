import json
import sqlite3
import unittest
from anime_approval_reconciler import reconcile

class ReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,status TEXT);
        CREATE TABLE notifications(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE verified_series_identity(notification_id INTEGER PRIMARY KEY,tvdb_id TEXT,episode_identity_verified INTEGER,eligible_for_acquisition INTEGER);
        CREATE TABLE migration_quarantined_series(series_id INTEGER PRIMARY KEY);
        CREATE TABLE series_rejection_blocks(series_id INTEGER PRIMARY KEY);
        CREATE TABLE episode_verification_v16(notification_id INTEGER PRIMARY KEY,evidence_json TEXT);
        CREATE TABLE confidence_shadow_v15(notification_id INTEGER PRIMARY KEY,evidence_json TEXT);
        INSERT INTO series VALUES(4,'tvdb','123','DISCOVERED');
        INSERT INTO notifications VALUES(7,'UNTRUSTED');
        INSERT INTO verified_series_identity VALUES(7,'123',0,0);
        """)
        shadow={"policy":{"enabled":True,"auto_approve_threshold":90},"score_points":95,"decision":"SHADOW_HIGH_CONFIDENCE","blockers":[]}
        verified={"decision":"AUTO_VERIFIED_CANDIDATE","episode_identity_verified":True,"blockers":[],"proposed_mapping":{"tvdb_id":"123","tvdb_season":1,"tvdb_episode":2}}
        self.db.execute("INSERT INTO confidence_shadow_v15 VALUES(?,?)",(7,json.dumps(shadow)))
        self.db.execute("INSERT INTO episode_verification_v16 VALUES(?,?)",(7,json.dumps(verified)))

    def test_approved_once(self):
        self.assertEqual(reconcile(self.db)["auto_approved"],1)
        self.assertEqual(reconcile(self.db)["auto_approved"],0)
        self.assertEqual(self.db.execute("SELECT decision FROM episode_approval_queue").fetchone()[0],"AUTO_APPROVED")

    def test_uncertain_episode_needs_review(self):
        self.db.execute("UPDATE episode_verification_v16 SET evidence_json=?",(json.dumps({"decision":"REVIEW_REQUIRED","episode_identity_verified":False,"blockers":["ORDERING_UNVERIFIED"],"proposed_mapping":None}),))
        self.assertEqual(reconcile(self.db)["needs_review"],1)

    def test_rejected_is_not_queued(self):
        self.db.execute("INSERT INTO series_rejection_blocks VALUES(4)")
        self.assertEqual(reconcile(self.db)["blocked"],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_approval_queue").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
