"""Offline candidate state transitions; no qBittorrent calls."""
import sqlite3
import unittest

from src.nextgen.storage.sonarr_candidates import (
    CandidateConflict, activate_candidate, fail_candidate, next_candidate,
    succeed_candidate,
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
