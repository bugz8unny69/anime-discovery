"""Offline E01-only selection, retries, and ownership fences."""
import sqlite3
import unittest

from anime_qb_e01_probe import start_e01_probe
from anime_qb_manifest_intake import submit_poll_pause
from anime_qb_ownership import OWNED, ownership
from test_anime_qb_manifest_intake import FakeQB, HASH, MAGNET, manifest


class SelectionQB(FakeQB):
    def __init__(self, *, ready_after=0, externally_owned=False):
        super().__init__(ready_after=ready_after, externally_owned=externally_owned)
        self.priorities={i:1 for i in range(12)}
        self.priority_calls=0
        self.start_calls=0
        self.fail_priority=False
        self.change_on_priority=False

    def torrent_files(self, infohash):
        files=super().torrent_files(infohash)
        for row in files:
            row["priority"]=self.priorities[row["index"]]
        if self.change_on_priority and self.priority_calls and files:
            files[0]["name"]="Season 02/Unexpected S02E01.mkv"
        return files

    def apply_stopped_file_selection(self, infohash, *, wanted_indices, skip_indices):
        self.priority_calls+=1
        if self.records[infohash]["state"] not in ("pausedDL","stoppedDL"):
            raise RuntimeError("not stopped")
        if self.fail_priority:
            raise RuntimeError("priority readback failed")
        if sorted(wanted_indices+skip_indices)!=list(range(12)):
            raise ValueError("not a complete file selection")
        self.priorities={i:(1 if i in wanted_indices else 0)
                         for i in range(12)}
        return {"wanted_indices":wanted_indices,"skip_indices":skip_indices}

    def start_selected_torrent(self, infohash, *, wanted_indices, skip_indices):
        self.start_calls+=1
        if self.records[infohash]["state"]!="pausedDL":
            raise RuntimeError("not stopped")
        if sorted(wanted_indices+skip_indices)!=list(range(12)):
            raise RuntimeError("incomplete")
        if any(self.priorities[i]!=(1 if i in wanted_indices else 0)
               for i in range(12)):
            raise RuntimeError("priority mismatch")
        self.records[infohash]["state"]="downloading"
        return True


class E01ProbeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)

    def get_stopped(self, qb):
        result=submit_poll_pause(self.db,HASH,MAGNET,qb,attempts=5,
                                 interval=0,sleep=lambda _:None)
        self.assertEqual(result["state"],"MANIFEST_READY")
        self.assertEqual(ownership(self.db,HASH),OWNED)
        return result

    def test_intake_e01_only_and_12_episode_pack(self):
        qb=SelectionQB()
        result=self.get_stopped(qb)
        started=start_e01_probe(self.db,HASH,qb,season=2,
                                stopped_manifest=result)
        self.assertEqual(started["state"],"PROBE_DOWNLOADING")
        self.assertEqual(started["file_index"],0)
        self.assertFalse(started["already_running"])
        self.assertEqual(qb.priorities[0],1)
        self.assertEqual(set(qb.priorities.values()),{0,1})
        self.assertEqual([i for i in range(1,12) if qb.priorities[i]],[])
        self.assertEqual(qb.start_calls,1)
        self.assertEqual(qb.records[HASH]["state"],"downloading")

    def test_repeat_while_e01_downloads_does_not_reset_or_restart(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        start_e01_probe(self.db,HASH,qb,season=2,
                        stopped_manifest=stopped)
        repeat=start_e01_probe(self.db,HASH,qb,season=2,
                               stopped_manifest=stopped)
        self.assertTrue(repeat["already_running"])
        self.assertEqual(qb.priority_calls,1)
        self.assertEqual(qb.start_calls,1)

    def test_wrong_confirmed_season_does_not_change_torrent(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        with self.assertRaises(ValueError):
            start_e01_probe(self.db,HASH,qb,season=1,
                            stopped_manifest=stopped)
        self.assertEqual(qb.priority_calls,0)
        self.assertEqual(qb.start_calls,0)
        self.assertEqual(qb.records[HASH]["state"],"pausedDL")

    def test_missing_e01_requires_another_release(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        subset=[f for f in stopped["files"] if f["index"]!=0]
        stopped["files"]=subset
        with self.assertRaises(ValueError):
            start_e01_probe(self.db,HASH,qb,season=2,
                            stopped_manifest=stopped)
        self.assertEqual(qb.start_calls,0)

    def test_priority_failure_stays_paused(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        qb.fail_priority=True
        with self.assertRaisesRegex(RuntimeError,"priority readback"):
            start_e01_probe(self.db,HASH,qb,season=2,
                            stopped_manifest=stopped)
        self.assertEqual(qb.start_calls,0)
        self.assertEqual(qb.records[HASH]["state"],"pausedDL")

    def test_manifest_change_after_priority_fails_stopped(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        qb.change_on_priority=True
        with self.assertRaisesRegex(RuntimeError,"manifest changed"):
            start_e01_probe(self.db,HASH,qb,season=2,
                            stopped_manifest=stopped)
        self.assertEqual(qb.start_calls,0)
        self.assertEqual(qb.records[HASH]["state"],"pausedDL")

    def test_active_unapproved_priorities_refuse_to_resume(self):
        qb=SelectionQB()
        stopped=self.get_stopped(qb)
        qb.records[HASH]["state"]="downloading"
        with self.assertRaisesRegex(RuntimeError,"Active torrent"):
            start_e01_probe(self.db,HASH,qb,season=2,
                            stopped_manifest=stopped)
        self.assertEqual(qb.priority_calls,0)
        self.assertEqual(qb.start_calls,0)

    def test_foreign_torrent_refuses_without_modifying(self):
        qb=SelectionQB(externally_owned=True)
        fake={"state":"MANIFEST_READY","infohash":HASH,
              "files":manifest()}
        with self.assertRaises(PermissionError):
            start_e01_probe(self.db,HASH,qb,season=2,
                            stopped_manifest=fake)
        self.assertEqual(qb.priority_calls,0)
        self.assertEqual(qb.start_calls,0)

    def test_wrong_or_missing_verified_stopped_manifest_refuses(self):
        qb=SelectionQB()
        good=self.get_stopped(qb)
        for bad in (None,{},{"state":"DEFERRED","infohash":HASH,
                             "files":good["files"]},
                    {"state":"MANIFEST_READY","infohash":"b"*40,
                     "files":good["files"]}):
            with self.assertRaises(ValueError):
                start_e01_probe(self.db,HASH,qb,season=2,
                                stopped_manifest=bad)
        self.assertEqual(qb.priority_calls,0)
        self.assertEqual(qb.start_calls,0)


if __name__=="__main__":
    unittest.main()
