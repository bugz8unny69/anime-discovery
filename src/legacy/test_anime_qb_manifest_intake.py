"""Offline normal-add / poll / pause tests (no actual torrents)."""
import sqlite3
import unittest

from anime_qb_manifest_intake import submit_poll_pause

HASH = "a" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


def manifest():
    return [
        {"index": i, "name": "Season 02/Anime S02E%02d.mkv" % (i + 1),
         "size": 1000, "priority": 1, "progress": 0.0}
        for i in range(12)
    ]


class FakeQB:
    def __init__(self, *, ready_after=1, externally_owned=False, visibility_delay=0):
        self.records = {}
        self.adds = 0
        self.stops = 0
        self.resumes = 0
        self.file_polls = 0
        self.ready_after = ready_after
        self.visibility_delay = visibility_delay
        self.contains_checks = 0
        self.externally_owned = externally_owned
        self.change_after_stop = False
        if externally_owned:
            self.records[HASH] = {"hash": HASH, "category": "other",
                                  "tags": "", "state": "downloading"}

    def contains_hash(self, infohash):
        self.contains_checks += 1
        return (infohash in self.records and
                self.contains_checks > self.visibility_delay)

    def torrent_identity(self, infohash):
        return self.records.get(infohash)

    def add_magnet(self, uri, *, category, tag):
        self.adds += 1
        self.records[HASH] = {"hash": HASH, "category": category,
                              "tags": tag, "state": "metaDL"}

    def torrent_files(self, infohash):
        self.file_polls += 1
        if self.file_polls <= self.ready_after:
            return []
        files = manifest()
        if self.change_after_stop and self.stops:
            files[0]["name"] = "Season 02/DIFFERENT S02E01.mkv"
        return files

    def stop_owned_torrent(self, infohash):
        self.stops += 1
        self.records[infohash]["state"] = "pausedDL"
        return "pausedDL"

    def resume_owned_metadata(self, infohash):
        if self.records[infohash]["state"] != "pausedDL":
            raise AssertionError("Must be stopped before metadata retry")
        self.resumes += 1
        self.records[infohash]["state"] = "metaDL"
        return True


class ManifestIntakeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)

    def run_intake(self, qb, *, attempts=5):
        return submit_poll_pause(self.db, HASH, MAGNET, qb, attempts=attempts,
                                 interval=1.0, sleep=lambda _: None)

    def test_add_normally_poll_then_pause_and_return_manifest(self):
        qb = FakeQB(ready_after=1)
        result = self.run_intake(qb)
        self.assertEqual(result["state"], "MANIFEST_READY")
        self.assertEqual(len(result["files"]), 12)
        self.assertEqual(qb.adds, 1)
        self.assertEqual(qb.stops, 1)
        self.assertEqual(qb.resumes, 0)
        self.assertEqual(qb.records[HASH]["state"], "pausedDL")
        self.assertGreaterEqual(qb.file_polls, 3)

    def test_journal_records_manifest_and_metadata_timeout(self):
        qb=FakeQB(ready_after=0)
        with self.assertLogs("anime_discovery.trial", level="INFO") as logs:
            result=self.run_intake(qb)
        self.assertEqual(result["state"],"MANIFEST_READY")
        self.assertIn("event=TORRENT_MANIFEST_READY", "\\n".join(logs.output))
        delayed=FakeQB(ready_after=100)
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            with self.assertLogs("anime_discovery.trial",level="INFO") as logs:
                state=submit_poll_pause(db,HASH,MAGNET,delayed,attempts=2,
                                        interval=0,sleep=lambda _:None)
            self.assertEqual(state["state"],"DEFERRED")
            self.assertIn("reason=METADATA_NOT_READY", "\\n".join(logs.output))

    def test_delayed_torrent_visibility_reconciles_without_duplicate_add(self):
        qb = FakeQB(ready_after=0, visibility_delay=4)
        result = self.run_intake(qb, attempts=6)
        self.assertEqual(result["state"], "MANIFEST_READY")
        self.assertEqual(qb.adds, 1)
        self.assertEqual(qb.stops, 1)
        self.assertGreater(qb.contains_checks, 4)

    def test_existing_external_torrent_is_never_paused(self):
        qb = FakeQB(externally_owned=True, ready_after=0)
        result = self.run_intake(qb)
        self.assertEqual(result["state"], "NEEDS_REVIEW")
        self.assertEqual(qb.adds, 0)
        self.assertEqual(qb.stops, 0)
        self.assertEqual(qb.resumes, 0)

    def test_metadata_delayed_stops_with_bounded_poll_window(self):
        qb = FakeQB(ready_after=100)
        result = self.run_intake(qb, attempts=3)
        self.assertEqual(result["state"], "DEFERRED")
        self.assertEqual(qb.adds, 1)
        self.assertEqual(qb.stops, 1)
        self.assertEqual(qb.records[HASH]["state"], "pausedDL")

    def test_retry_uses_existing_magnet_and_restarts_metadata_only(self):
        qb = FakeQB(ready_after=5)
        first = self.run_intake(qb, attempts=2)
        self.assertEqual(first["state"], "DEFERRED")
        self.assertEqual(qb.stops, 1)
        second = self.run_intake(qb, attempts=4)
        self.assertEqual(second["state"], "MANIFEST_READY")
        self.assertEqual(qb.adds, 1)
        self.assertEqual(qb.resumes, 1)
        self.assertEqual(qb.stops, 2)

    def test_refuses_manifest_changed_during_pause(self):
        qb = FakeQB(ready_after=0)
        qb.change_after_stop = True
        with self.assertRaisesRegex(ValueError, "changed during pause"):
            self.run_intake(qb)
        self.assertEqual(qb.records[HASH]["state"], "pausedDL")

    def test_submission_deduplication_after_manifest_is_ready(self):
        qb = FakeQB(ready_after=0)
        self.assertEqual(self.run_intake(qb)["state"], "MANIFEST_READY")
        self.assertEqual(self.run_intake(qb)["state"], "MANIFEST_READY")
        self.assertEqual(qb.adds, 1)

    def test_rejects_outside_poll_limits_before_external_submission(self):
        qb = FakeQB()
        with self.assertRaises(ValueError):
            self.run_intake(qb, attempts=0)
        self.assertEqual(qb.adds, 0)


if __name__ == "__main__":
    unittest.main()
