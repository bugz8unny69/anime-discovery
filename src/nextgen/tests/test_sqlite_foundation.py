"""Offline tests for the NextGen SQLite foundation; never touches production."""
import os
import sqlite3
import tempfile
import unittest

from src.nextgen.storage.sqlite import connect, initialize, accept_event, save_identity


class SQLiteFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.sqlite")
        self.db = connect(self.path)
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def candidate(self, episodes=None):
        return {"schema_version": 2, "anime": {
            "anidb_id": 123, "tvdb_series_id": 456, "title": "Test Anime"},
            "episodes": [] if episodes is None else episodes}

    def test_every_duplicate_delivery_has_independent_trace_and_history(self):
        a = accept_event(self.db, "autobrr", b"same")
        b = accept_event(self.db, "autobrr", b"same")
        self.assertNotEqual(a, b)
        self.assertEqual(self.db.execute("SELECT count(*) FROM webhook_events").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM event_history").fetchone()[0], 2)

    def test_pending_work_survives_database_reopen(self):
        event = accept_event(self.db, "autobrr", b"payload")
        self.db.close()
        self.db = connect(self.path)
        self.assertEqual(self.db.execute("SELECT state FROM webhook_events WHERE event_id=?",
                                         (event,)).fetchone()[0], "PENDING")

    def test_valid_series_without_episodes(self):
        event = accept_event(self.db, "autobrr", b"batch")
        save_identity(self.db, event, self.candidate())
        self.assertEqual(self.db.execute("SELECT count(*) FROM identity_results").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM identified_episodes").fetchone()[0], 0)

    def test_verified_episode_links_reused_across_events(self):
        candidate = self.candidate([{"anidb_episode_id": 987}])
        for _ in range(2):
            save_identity(self.db, accept_event(self.db, "autobrr", b"episode"), candidate)
        self.assertEqual(self.db.execute("SELECT count(*) FROM identified_episodes").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM result_episode_links").fetchone()[0], 2)

    def test_invalid_identity_keeps_original_event(self):
        event = accept_event(self.db, "autobrr", b"invalid")
        candidate = self.candidate([{"anidb_episode_id": -1}])
        with self.assertRaises(ValueError):
            save_identity(self.db, event, candidate)
        self.assertEqual(self.db.execute("SELECT count(*) FROM identity_results").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT state FROM webhook_events WHERE event_id=?",
                                         (event,)).fetchone()[0], "PENDING")

    def test_foreign_keys_reject_unknown_event(self):
        with self.assertRaises(sqlite3.IntegrityError):
            save_identity(self.db, 999, self.candidate())
        self.assertEqual(self.db.execute("SELECT count(*) FROM identified_anime").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
