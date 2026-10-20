"""Fresh SQLite integration tests for Autobrr intake and series UI lifecycle."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_webhook_processing import approve, receive
from anime_series_lifecycle import action, inspect, notifications
from anime_release_matching import resolve_release
from anime_flat_config import validate_config

HASH = "a" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


class WebhookLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "anime.db"
        initialize(self.path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")

    def event(self, episode=2, guid="release-2", **changes):
        data = dict(release_name="Example.S01E02", source_guid=guid,
                    info_hash=HASH, tvdb_id=123, anidb_id=456,
                    season=1, episode=episode, magnet_uri=MAGNET)
        data.update(changes)
        return data

    def test_full_autobrr_payload_creates_series_dispatch_and_job(self):
        result = receive(self.db, self.event())
        self.assertTrue(result["queued"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM series").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT season,episode FROM episodes").fetchone(), (1,2))
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0], "CLAIMED")
        self.assertEqual(self.db.execute("SELECT state FROM daemon_jobs").fetchone()[0], "READY")
        self.assertEqual(self.db.execute("SELECT count(*) FROM external_actions").fetchone()[0], 0)

    def test_duplicate_webhook_has_no_duplicate_jobs(self):
        first = receive(self.db, self.event())
        second = receive(self.db, self.event())
        self.assertEqual(first["notification_id"], second["notification_id"])
        self.assertFalse(second["queued"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 1)

    def test_webhook_pending_and_repeated_review_report_actual_status(self):
        payload=dict(release_name="[Group] Solo Leveling - 01",
                     source_guid="solo-guid",info_hash=HASH)
        first=receive(self.db,payload)
        self.assertEqual(first["identity_status"],"IDENTIFYING")
        self.assertTrue(first["identification_pending"])
        self.assertFalse(first["needs_review"])
        self.db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=?",
                        (first["notification_id"],))
        second=receive(self.db,payload)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["identity_status"],"NEEDS_REVIEW")
        self.assertTrue(second["needs_review"])
        self.assertFalse(second["identification_pending"])

    def test_guid_conflicting_hash_rejected(self):
        receive(self.db, self.event())
        with self.assertRaisesRegex(ValueError,"different torrent"):
            receive(self.db, self.event(info_hash="b"*40,magnet_uri="magnet:?xt=urn:btih:"+"b"*40))
        self.assertEqual(self.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 1)

    def test_missing_identity_stays_in_inbox(self):
        receive(self.db, dict(name="Unknown Episode",torrentHash=HASH))
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 1)
        result = approve(self.db, 1, dict(tvdb_id=123,anidb_id=456,season=1,episode=2))
        self.assertTrue(result["queued"])
        self.assertEqual(json.loads(self.db.execute(
            "SELECT payload_json FROM daemon_jobs").fetchone()[0])["magnet_uri"], MAGNET)

    def test_failed_approval_leaves_no_approval_or_job(self):
        receive(self.db, dict(release_name="Unverified",info_hash=HASH))
        with self.assertRaises(ValueError):
            approve(self.db,1,dict(tvdb_id=123,anidb_id=456,season=1,episode=2,
                                   magnet_uri="magnet:?xt=urn:btih:"+"b"*40))
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],0)

    def test_reject_clear_inspect_reset_then_new_webhook(self):
        first = receive(self.db,self.event())
        sid = first["series_id"]
        self.assertEqual(len(inspect(self.db,sid)["releases"]),1)
        action(self.db,sid,"reject")
        self.assertEqual(self.db.execute("SELECT state FROM daemon_jobs").fetchone()[0],"BLOCKED")
        with self.assertRaisesRegex(ValueError,"rejected"):
            receive(self.db,self.event(guid="release-3",episode=3))
        action(self.db,sid,"clear-history")
        self.assertTrue(inspect(self.db,sid)["rejected"])
        self.assertFalse(any(n[0]==first["notification_id"] for n in notifications(self.db)))
        action(self.db,sid,"reset")
        self.assertFalse(inspect(self.db,sid)["rejected"])
        newer = receive(self.db,self.event(guid="release-4",episode=4))
        self.assertTrue(newer["queued"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],2)

    def test_episode_identity_conflicts_rejected_on_repeat(self):
        receive(self.db,self.event())
        with self.assertRaisesRegex(ValueError,"conflicts"):
            receive(self.db,self.event(episode=9))
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],1)

    def test_approval_missing_magnet_generates_bounded_magnet(self):
        receive(self.db,self.event(guid="omitted-magnet",magnet_uri=""))
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],1)

    def test_alias_mapping_handles_standard_and_fansub_episode(self):
        mappings = {"Example Show": {"tvdb_id": 123, "anidb_id": 456, "season": 1}}
        self.assertEqual(resolve_release("Example.Show.S01E02.1080p", mappings)["episode"], 2)
        self.assertEqual(resolve_release("[SubsPlease] Example Show - 03 (1080p)", mappings)["episode"], 3)
        self.assertIsNone(resolve_release("Unrelated Show S01E03", mappings))
        raw = dict(release_name="[SubsPlease] Example Show - 02 (1080p)",
                   torrentHash=HASH, guid="mapped-episode")
        result = receive(self.db, raw, series_map=mappings)
        self.assertTrue(result["queued"])
        self.assertEqual(self.db.execute("SELECT season,episode FROM episode_dispatch").fetchone(), (1,2))

    def test_ambiguous_alias_does_not_queue(self):
        mappings = {"Example Show": {"tvdb_id":123,"anidb_id":456},
                    "Example.Show":{"tvdb_id":321,"anidb_id":654}}
        result = receive(self.db, dict(release_name="Example Show S01E02",info_hash=HASH),
                         series_map=mappings)
        self.assertTrue(result["received"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],0)

    def test_config_accepts_series_mappings(self):
        c=validate_config({"identity":{"series_map":{"Example Show":{
            "tvdb_id":123,"anidb_id":456,"season":1}}}}, {})
        self.assertEqual(c["settings"]["identity"]["series_map"]["Example Show"]["tvdb_id"],123)
        with self.assertRaises(ValueError):
            validate_config({"identity":{"series_map":{"Invalid":{"tvdb_id":123}}}}, {})


if __name__ == "__main__":
    unittest.main()
