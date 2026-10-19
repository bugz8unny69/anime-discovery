import sqlite3
import unittest
from anime_approval_handoff import handoff
from anime_identity_rejection_gate import SeriesBlocked

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,status TEXT);
        CREATE TABLE notifications(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE verified_series_identity(notification_id INTEGER PRIMARY KEY,tvdb_id TEXT,episode_identity_verified INTEGER,eligible_for_acquisition INTEGER);
        CREATE TABLE migration_quarantined_series(series_id INTEGER PRIMARY KEY);
        CREATE TABLE series_rejection_blocks(series_id INTEGER PRIMARY KEY);
        INSERT INTO series VALUES(4,'tvdb','123','DISCOVERED');
        INSERT INTO notifications VALUES(7,'UNTRUSTED');
        INSERT INTO verified_series_identity VALUES(7,'123',0,0);
        """)
        self.shadow={"policy":{"enabled":True,"auto_approve_threshold":90},"score_points":95,"decision":"SHADOW_HIGH_CONFIDENCE","blockers":[]}
        self.verified={"decision":"AUTO_VERIFIED_CANDIDATE","episode_identity_verified":True,"blockers":[],"proposed_mapping":{"tvdb_id":"123","tvdb_season":1,"tvdb_episode":2}}

    def test_automatic_handoff_is_idempotent(self):
        self.assertEqual(handoff(self.db,7,self.shadow,self.verified)["decision"],"AUTO_APPROVED")
        self.assertEqual(handoff(self.db,7,self.shadow,self.verified)["decision"],"AUTO_APPROVED")
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_approval_queue").fetchone()[0],1)

    def test_rejection_blocks_queue(self):
        self.db.execute("INSERT INTO series_rejection_blocks VALUES(4)")
        with self.assertRaises(SeriesBlocked):
            handoff(self.db,7,self.shadow,self.verified)
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_approval_queue").fetchone()[0],0)

    def test_uncertain_ordering_needs_review_without_fake_episode(self):
        self.verified["proposed_mapping"]=None
        self.verified["episode_identity_verified"]=False
        result=handoff(self.db,7,self.shadow,self.verified)
        self.assertEqual(result["decision"],"NEEDS_REVIEW")
        self.assertIsNone(result["episode"])
        self.assertIsNone(self.db.execute("SELECT episode FROM episode_approval_queue").fetchone()[0])

if __name__=="__main__":
    unittest.main()
