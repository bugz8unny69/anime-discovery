"""Offline conditional byte budget, persistent reservations and journal evidence."""
import sqlite3
import unittest

from anime_trial_policy import record_verified_window, window_for
from anime_trial_size_policy import (
    MB, TrialSizeRejected, size_limits, decide_trial_size,
    authorize_manifest_sizes,
)


class TrialSizeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        record_verified_window(
            self.db, tvdb_id=123, anidb_id=456, season=1,
            unit_key="ongoing:1001", mode="ONGOING", start_episode=1001,
            evidence_ref="tvdb:123:verified:1001")
        self.window = window_for(self.db, tvdb_id=123, anidb_id=456, season=1)

    def reserve(self, sizes, torrent_character="a"):
        return authorize_manifest_sizes(
            self.db, window=self.window, infohash=torrent_character * 40,
            episode_files={ep: {"index": ep - 1001, "size": mb * MB}
                           for ep, mb in sizes.items()})

    def test_six_known_700_400_each_is_eligible_and_logged_as_exception(self):
        incoming = {1001: 700, **{n: 400 for n in range(1002, 1007)}}
        with self.assertLogs("anime_discovery.trial", level="INFO") as lines:
            outcome = self.reserve(incoming)
        self.assertTrue(outcome["complete_six"])
        self.assertEqual(outcome["trial_total_bytes"], 2700 * MB)
        text = "\n".join(lines.output)
        self.assertIn("reason=FULL_SIX_OVERRIDES_EPISODE_LIMIT", text)
        self.assertIn("episode=1001", text)
        self.assertIn("action=ELIGIBLE", text)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 6)

    def test_partial_700_mb_episode_is_hard_blocked_and_not_reserved(self):
        with self.assertLogs("anime_discovery.trial", level="WARNING") as lines:
            with self.assertRaises(TrialSizeRejected) as ctx:
                self.reserve({1001: 700})
        self.assertEqual(ctx.exception.reason, "EPISODE_SIZE_EXCEEDED")
        self.assertIn("action=NEEDS_REVIEW", "\n".join(lines.output))
        self.assertIn("reason=EPISODE_SIZE_EXCEEDED", "\n".join(lines.output))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 0)

    def test_full_six_over_3000_mb_is_blocked_atomically(self):
        with self.assertRaises(TrialSizeRejected) as ctx:
            self.reserve({n: 550 for n in range(1001, 1007)})
        self.assertEqual(ctx.exception.reason, "TRIAL_TOTAL_EXCEEDED")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 0)

    def test_separately_arriving_episodes_accumulate_across_torrents(self):
        for i in range(5):
            outcome = self.reserve({1001 + i: 550}, chr(ord("a") + i))
            self.assertFalse(outcome["complete_six"])
        with self.assertRaises(TrialSizeRejected) as ctx:
            self.reserve({1006: 550}, "f")
        self.assertEqual(ctx.exception.reason, "TRIAL_TOTAL_EXCEEDED")
        self.assertEqual(self.db.execute(
            "SELECT SUM(size_bytes) FROM anime_trial_size_reservations").fetchone()[0],
            2750 * MB)

    def test_sixth_separately_arriving_large_episode_is_allowed_if_total_known(self):
        for i in range(5):
            self.reserve({1001 + i: 440}, chr(ord("a") + i))
        with self.assertLogs("anime_discovery.trial", level="INFO") as lines:
            result = self.reserve({1006: 800}, "f")
        self.assertEqual(result["trial_total_bytes"], 3000 * MB)
        self.assertIn("reason=FULL_SIX_OVERRIDES_EPISODE_LIMIT",
                      "\n".join(lines.output))

    def test_identical_retry_idempotent_conflict_fails_closed(self):
        self.reserve({1001: 450})
        with self.assertLogs("anime_discovery.trial", level="INFO") as lines:
            self.reserve({1001: 450})
        self.assertIn("reason=ALREADY_RESERVED", "\n".join(lines.output))
        for sizes, char, reason in (
            ({1001: 450}, "b", "CONFLICTING_EPISODE_RESERVATION"),
            ({1001: 451}, "a", "CONFLICTING_EPISODE_RESERVATION")):
            with self.assertRaises(TrialSizeRejected) as ctx:
                self.reserve(sizes, char)
            self.assertEqual(ctx.exception.reason, reason)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 1)

    def test_settings_validation_and_decimal_mb_exact_boundary(self):
        self.assertEqual(size_limits()["max_episode_mb"], 600)
        for settings in (
            {"max_episode_mb": True, "max_six_episode_mb": 3000},
            {"max_episode_mb": 0, "max_six_episode_mb": 3000},
            {"max_episode_mb": 600},
            {"max_episode_mb": 600, "max_six_episode_mb": "3000"},
        ):
            with self.assertRaises(ValueError):
                size_limits(settings)
        self.assertTrue(decide_trial_size({1: 600 * MB}, start_episode=1)["eligible"])
        with self.assertRaises(TrialSizeRejected):
            decide_trial_size({1: 600 * MB + 1}, start_episode=1)

    def test_outside_window_and_index_reuse_do_not_reserve(self):
        for episode_files in (
            {1007: {"index": 0, "size": 450 * MB}},
            {1001: {"index": -1, "size": 450 * MB}},
            {1001: {"index": 0, "size": 450 * MB},
             1002: {"index": 0, "size": 400 * MB}},
        ):
            with self.assertRaises(ValueError):
                authorize_manifest_sizes(self.db, window=self.window,
                    infohash="a" * 40, episode_files=episode_files)
        # Invalid caller arguments can be rejected before even creating a
        # ledger; make the empty-table assertion independently of that path.
        from anime_trial_size_policy import ensure_schema
        ensure_schema(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 0)

    def test_window_identity_is_not_caller_controlled(self):
        altered = {**self.window, "end": 1007}
        with self.assertRaises(PermissionError):
            authorize_manifest_sizes(self.db, window=altered, infohash="a" * 40,
                                     episode_files={1001: {"index": 0, "size": 100 * MB}})


if __name__ == "__main__":
    unittest.main()
