"""Offline candidate state transitions; no qBittorrent calls."""
import sqlite3
import unittest

from src.nextgen.storage.sonarr_candidates import (
    CandidateConflict, activate_candidate, fail_candidate, next_candidate,
    succeed_candidate, mark_published,
)

FIRST='a'*40
SECOND='b'*40


class CandidateStateTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute(
            "CREATE TABLE sonarr_episode_candidates("
            "plan_id INTEGER,tvdb_episode INTEGER,rank INTEGER,info_hash TEXT,"
            "state TEXT DEFAULT 'READY',reason_code TEXT,"
            "PRIMARY KEY(plan_id,tvdb_episode,rank))")
        self.db.executemany(
            "INSERT INTO sonarr_episode_candidates"
            "(plan_id,tvdb_episode,rank,info_hash) VALUES(1,2,?,?)",
            ((1,FIRST),(2,SECOND)))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_failure_activates_next_candidate_without_reusing_first(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.assertEqual(next_candidate(self.db,plan_id=1,episode=2),(1,FIRST))
            self.assertTrue(activate_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST))
            self.assertFalse(activate_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST))
            with self.assertRaises(CandidateConflict):
                activate_candidate(self.db,plan_id=1,episode=2,info_hash=SECOND)
            fail_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST,
                           reason_code='TORRENT_METADATA_INVALID')
            self.assertEqual(next_candidate(self.db,plan_id=1,episode=2),(2,SECOND))
            self.assertTrue(activate_candidate(self.db,plan_id=1,episode=2,info_hash=SECOND))
            succeed_candidate(self.db,plan_id=1,episode=2,info_hash=SECOND)
            self.assertIsNone(next_candidate(self.db,plan_id=1,episode=2))
        self.assertEqual(self.db.execute(
            "SELECT state FROM sonarr_episode_candidates ORDER BY rank").fetchall(),
            [('FAILED',),('SUCCEEDED',)])

    def test_published_sonarr_event_marks_only_its_active_candidate(self):
        self.db.executescript("""
            CREATE TABLE incoming_events(event_id INTEGER,source TEXT);
            CREATE TABLE jobs(job_id INTEGER,event_id INTEGER,kind TEXT,
                              created_by_job_id INTEGER,payload_json TEXT);
            CREATE TABLE trial_plans(plan_id INTEGER);
            CREATE TABLE sonarr_episode_selections(
                plan_id INTEGER,tvdb_episode INTEGER,info_hash TEXT);
            INSERT INTO incoming_events VALUES(25,'sonarr-discovery');
            INSERT INTO incoming_events VALUES(26,'other');
            INSERT INTO jobs VALUES(2,25,'DISCOVER_SONARR_BACKFILL',NULL,'{"plan_id":1}');
            INSERT INTO jobs VALUES(3,25,'VERIFY_RELEASE',2,'{}');
            INSERT INTO trial_plans VALUES(1);
        """)
        self.db.execute(
            "INSERT INTO sonarr_episode_selections VALUES(1,2,?)",(FIRST,))
        self.db.commit()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            activate_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST)
            self.assertFalse(mark_published(self.db,event_id=26,info_hash=FIRST))
            self.assertTrue(mark_published(self.db,event_id=25,info_hash=FIRST))
        self.assertEqual(self.db.execute(
            "SELECT state FROM sonarr_episode_candidates WHERE rank=1").fetchone(),
            ('SUCCEEDED',))

    def test_untried_candidate_cannot_fail_or_complete(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(CandidateConflict):
                fail_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST,
                               reason_code='TORRENT_METADATA_INVALID')
            with self.assertRaises(CandidateConflict):
                succeed_candidate(self.db,plan_id=1,episode=2,info_hash=FIRST)
            with self.assertRaises(CandidateConflict):
                activate_candidate(self.db,plan_id=1,episode=2,info_hash=SECOND)
