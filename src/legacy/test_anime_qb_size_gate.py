"""Offline qB manifest size admission before priorities or E01 download."""
import sqlite3
import unittest

from anime_qb_e01_probe import start_e01_probe
from anime_qb_manifest_intake import submit_poll_pause
from anime_trial_policy import record_verified_window, window_for
from anime_trial_size_policy import MB, TrialSizeRejected
from test_anime_qb_e01_probe import SelectionQB, HASH, MAGNET


class SizedQB(SelectionQB):
    def __init__(self, sizes, *, only_first=False):
        super().__init__(ready_after=0)
        self.sizes = sizes
        self.only_first = only_first

    def torrent_files(self, infohash):
        files = super().torrent_files(infohash)
        for row in files:
            i = row["index"]
            row["size"] = self.sizes[i] * MB
            if self.only_first and 1 <= i <= 5:
                row["name"] = "Season 02/notes-%d.txt" % i
        return files


class QBSizeGateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        record_verified_window(self.db, tvdb_id=123, anidb_id=456, season=2,
            unit_key="season", mode="SEASON", start_episode=1,
            evidence_ref="anime-lists:123:456:season2")
        self.window = window_for(self.db, tvdb_id=123, anidb_id=456, season=2)

    def stopped(self, qb):
        out = submit_poll_pause(self.db, HASH, MAGNET, qb, attempts=4,
                                interval=0, sleep=lambda _: None)
        self.assertEqual(out["state"], "MANIFEST_READY")
        return out

    def test_batch_total_under_3000_overrides_700_mb_first_episode(self):
        qb = SizedQB([700, 400, 400, 400, 400, 400] + [900] * 6)
        stopped = self.stopped(qb)
        with self.assertLogs("anime_discovery.trial", level="INFO") as log:
            result = start_e01_probe(self.db, HASH, qb, season=2,
                        stopped_manifest=stopped, verified_window=self.window,
                        verified_episode_map={n:n for n in range(1, 13)})
        self.assertEqual(result["file_index"], 0)
        self.assertEqual(qb.start_calls, 1)
        self.assertEqual([qb.priorities[i] for i in range(12)], [1] + [0] * 11)
        self.assertIn("reason=FULL_SIX_OVERRIDES_EPISODE_LIMIT", "\n".join(log.output))
        rows = self.db.execute("""SELECT COUNT(*),SUM(size_bytes)
            FROM anime_trial_size_reservations""").fetchone()
        self.assertEqual(rows, (6, 2700 * MB))

    def test_3000_mb_trial_total_exceeded_remains_paused(self):
        qb = SizedQB([550] * 12)
        stopped = self.stopped(qb)
        with self.assertRaises(TrialSizeRejected) as failed:
            start_e01_probe(self.db, HASH, qb, season=2,
                stopped_manifest=stopped, verified_window=self.window,
                verified_episode_map={n:n for n in range(1, 13)})
        self.assertEqual(failed.exception.reason, "TRIAL_TOTAL_EXCEEDED")
        self.assertEqual(qb.priority_calls, 0)
        self.assertEqual(qb.start_calls, 0)
        self.assertEqual(qb.records[HASH]["state"], "pausedDL")

    def test_partially_known_700_mb_first_episode_refused(self):
        qb = SizedQB([700] + [400] * 11, only_first=True)
        stopped = self.stopped(qb)
        with self.assertRaises(TrialSizeRejected) as failed:
            start_e01_probe(self.db, HASH, qb, season=2,
                stopped_manifest=stopped, verified_window=self.window,
                verified_episode_map={1:1, **{n:n for n in range(7,13)}})
        self.assertEqual(failed.exception.reason, "EPISODE_SIZE_EXCEEDED")
        self.assertEqual(qb.priority_calls, 0)
        self.assertEqual(qb.start_calls, 0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0], 0)

    def test_dashboard_limits_are_effective_at_manifest_boundary(self):
        qb = SizedQB([500] * 12)
        stopped = self.stopped(qb)
        with self.assertRaises(TrialSizeRejected) as failed:
            start_e01_probe(self.db, HASH, qb, season=2,
                stopped_manifest=stopped, verified_window=self.window,
                verified_episode_map={n:n for n in range(1,13)},
                size_settings={"max_episode_mb": 600, "max_six_episode_mb": 2500})
        self.assertEqual(failed.exception.reason, "TRIAL_TOTAL_EXCEEDED")
        self.assertEqual(qb.start_calls, 0)


if __name__ == "__main__":
    unittest.main()
