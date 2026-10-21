"""Offline episode acquisition claim guard tests."""
import sqlite3
import unittest
from anime_episode_acquisition_guard import competing_claim,CompetingEpisodeAcquisition

class CompetingAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
        CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT);
        CREATE TABLE episode_dispatch(notification_id INTEGER PRIMARY KEY,
          series_id INTEGER,season INTEGER,episode INTEGER,state TEXT);
        INSERT INTO series VALUES(1,'tvdb','123');
        INSERT INTO series VALUES(2,'tvdb','456');
        INSERT INTO episode_dispatch VALUES(10,1,1,1,'CLAIMED');
        """)
    def test_second_group_same_episode_is_competing(self):
        self.assertEqual(competing_claim(self.db,"123",1,1,11),10)
    def test_same_notification_other_episode_and_series_are_not_blocked(self):
        self.assertIsNone(competing_claim(self.db,"123",1,1,10))
        self.assertIsNone(competing_claim(self.db,"123",1,2,11))
        self.assertIsNone(competing_claim(self.db,"123",2,1,11))
        self.assertIsNone(competing_claim(self.db,"456",1,1,11))
    def test_stale_claim_fails_closed_until_reconciled(self):
        self.db.execute("UPDATE episode_dispatch SET state='BLOCKED' WHERE notification_id=10")
        self.assertEqual(competing_claim(self.db,"123",1,1,12),10)
    def test_conflict_exposes_safe_notification_reference(self):
        issue=CompetingEpisodeAcquisition(10)
        self.assertEqual(issue.notification_id,10)
        self.assertNotIn("release",str(issue).lower())

if __name__=="__main__":
    unittest.main()
