import sqlite3
import unittest
from unittest.mock import patch
from anime_acquisition_gate import approved_dispatch

class AcquisitionGateTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE episode_dispatch(notification_id INTEGER,series_id INTEGER,season INTEGER,episode INTEGER,state TEXT);
          CREATE TABLE episode_approval_queue(notification_id INTEGER,decision TEXT,season INTEGER,episode INTEGER);
          CREATE TABLE episode_verification_v16(notification_id INTEGER,verified INTEGER,evidence_json TEXT);
          INSERT INTO episode_dispatch VALUES(4,8,1,2,'CLAIMED');
          INSERT INTO episode_approval_queue VALUES(4,'AUTO_APPROVED',1,2);
          INSERT INTO episode_verification_v16 VALUES(4,1,'{}');
        """)

    @patch("anime_acquisition_gate.resolve_notification",return_value=8)
    def test_approved(self,_):
        self.assertEqual(approved_dispatch(self.db,4)["episode"],2)

    @patch("anime_acquisition_gate.resolve_notification",return_value=8)
    def test_unverified_fails_closed(self,_):
        self.db.execute("UPDATE episode_verification_v16 SET verified=0")
        with self.assertRaises(ValueError):
            approved_dispatch(self.db,4)

    @patch("anime_acquisition_gate.resolve_notification",return_value=8)
    def test_episode_mismatch_fails_closed(self,_):
        self.db.execute("UPDATE episode_dispatch SET episode=3")
        with self.assertRaises(ValueError):
            approved_dispatch(self.db,4)

if __name__=="__main__":
    unittest.main()
