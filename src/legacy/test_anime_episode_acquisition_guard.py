"""Offline atomic episode acquisition arbitration."""
import sqlite3
import unittest
from anime_episode_acquisition_guard import reserve,mark_staged

class EpisodeSlots(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE daemon_jobs(id INTEGER PRIMARY KEY,kind TEXT,state TEXT,last_error TEXT,subject_key TEXT,available_at REAL);
          CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT);
          CREATE TABLE episode_dispatch(notification_id INTEGER PRIMARY KEY,
            series_id INTEGER,season INTEGER,episode INTEGER,state TEXT);
          INSERT INTO series VALUES(1,'tvdb','123');
          INSERT INTO series VALUES(2,'tvdb','456');
          INSERT INTO episode_dispatch VALUES(10,1,1,1,'CLAIMED');
          INSERT INTO episode_dispatch VALUES(11,1,1,1,'CLAIMED');
          INSERT INTO episode_dispatch VALUES(12,1,1,2,'CLAIMED');
          INSERT INTO episode_dispatch VALUES(13,2,1,1,'CLAIMED');
        """)
    def test_one_active_other_group_waits_and_distinct_episodes_continue(self):
        self.assertEqual(reserve(self.db,10),"OWNER")
        self.assertEqual(reserve(self.db,11),"ON_HOLD")
        self.assertEqual(reserve(self.db,12),"OWNER")
        self.assertEqual(reserve(self.db,13),"OWNER")
    def test_trial_stage_closes_competitors_not_manual_keep(self):
        reserve(self.db,10)
        with self.assertRaises(ValueError):
            mark_staged(self.db,10)
        self.db.execute("UPDATE episode_dispatch SET state='DONE' WHERE notification_id=10")
        mark_staged(self.db,10)
        self.assertEqual(reserve(self.db,11),"SKIPPED_DUPLICATE")
        self.assertEqual(reserve(self.db,10),"OWNER")
    def test_staged_release_wakes_held_jobs_and_is_idempotent(self):
        reserve(self.db,10)
        self.db.execute("""INSERT INTO daemon_jobs VALUES
            (1,'claimed_acquisition','DEFERRED','ON_HOLD','11',3600)""")
        self.db.execute("UPDATE episode_dispatch SET state='DONE' WHERE notification_id=10")
        mark_staged(self.db,10)
        mark_staged(self.db,10)
        self.assertEqual(self.db.execute("SELECT available_at FROM daemon_jobs WHERE id=1").fetchone()[0],0)
        self.assertEqual(reserve(self.db,11),"SKIPPED_DUPLICATE")
    def test_active_claim_survives_restart_and_uncertain_failure(self):
        reserve(self.db,10)
        self.assertEqual(reserve(self.db,11),"ON_HOLD")
        self.db.execute("UPDATE episode_dispatch SET state='NEEDS_REVIEW' WHERE notification_id=10")
        self.assertEqual(reserve(self.db,11),"ON_HOLD")

if __name__=="__main__":
    unittest.main()
