import sqlite3
import time
import unittest
from unittest.mock import patch
from anime_acquisition_finalize import finalize_acquisition

class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.execute("CREATE TABLE daemon_jobs(id INTEGER,state TEXT,lease_token TEXT,lease_until REAL,kind TEXT,subject_key TEXT)")
        self.db.execute("CREATE TABLE episode_dispatch(notification_id INTEGER,state TEXT,last_error TEXT,updated_at INTEGER)")
        self.db.execute("CREATE TABLE torrent_recovery_records(notification_id INTEGER,staged_path TEXT,sha256 TEXT)")
        self.db.execute("INSERT INTO daemon_jobs VALUES(1,'LEASED','current',9999999999,'claimed_acquisition','7')")
        self.db.execute("INSERT INTO episode_dispatch VALUES(7,'CLAIMED',NULL,0)")
        self.db.execute("INSERT INTO torrent_recovery_records VALUES(7,'/tmp/example.mkv','abc')")
    def tearDown(self):
        self.db.close()
    def test_valid_lease_completes(self):
        with patch("anime_acquisition_finalize.approved_dispatch",return_value={"notification_id":7}):
            finalize_acquisition(self.db,1,"current",7,now=100)
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"DONE")
    def test_stale_token_does_not_complete(self):
        with patch("anime_acquisition_finalize.approved_dispatch") as approval:
            with self.assertRaisesRegex(ValueError,"Stale"):
                finalize_acquisition(self.db,1,"old",7,now=100)
            approval.assert_not_called()
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"CLAIMED")
    def test_missing_record_does_not_complete(self):
        self.db.execute("DELETE FROM torrent_recovery_records")
        with patch("anime_acquisition_finalize.approved_dispatch",return_value={}):
            with self.assertRaisesRegex(ValueError,"recovery"):
                finalize_acquisition(self.db,1,"current",7,now=100)
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"CLAIMED")

if __name__=="__main__":
    unittest.main()
