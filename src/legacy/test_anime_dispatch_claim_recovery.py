import sqlite3
import unittest
from anime_dispatch_queue import reclaim_expired_claims

class DispatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.db.executescript("""
            CREATE TABLE series(id INTEGER,status TEXT);
            CREATE TABLE episode_approval_queue(notification_id INTEGER,decision TEXT);
            CREATE TABLE episode_dispatch(notification_id INTEGER,series_id INTEGER,
                season INTEGER,episode INTEGER,state TEXT,attempts INTEGER,
                updated_at INTEGER,last_error TEXT);
            CREATE TABLE series_rejection_blocks(series_id INTEGER);
            CREATE TABLE migration_quarantined_series(series_id INTEGER);
            CREATE TABLE daemon_jobs(kind TEXT,subject_key TEXT);
            INSERT INTO series VALUES(2,'APPROVED');
            INSERT INTO episode_approval_queue VALUES(7,'AUTO_APPROVED');
            INSERT INTO episode_dispatch VALUES(7,2,1,1,'CLAIMED',1,100,NULL);
        """)
    def tearDown(self):
        self.db.close()
    def test_abandoned_claim_reclaimed(self):
        self.assertEqual(reclaim_expired_claims(self.db,now=1000,older_than_seconds=300),1)
        self.assertEqual(self.db.execute('SELECT state FROM episode_dispatch').fetchone()[0],'READY')
    def test_existing_daemon_job_prevents_reclaim(self):
        self.db.execute("INSERT INTO daemon_jobs VALUES('claimed_acquisition','7')")
        self.assertEqual(reclaim_expired_claims(self.db,now=1000,older_than_seconds=300),0)
        self.assertEqual(self.db.execute('SELECT state FROM episode_dispatch').fetchone()[0],'CLAIMED')

if __name__=='__main__':
    unittest.main()
