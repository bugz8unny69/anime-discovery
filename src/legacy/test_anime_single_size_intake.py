"""Offline qB metadata hard size gate for independently arriving episodes."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_webhook_processing import receive
from anime_single_size_intake import admit_single_episode
from anime_trial_size_policy import MB, TrialSizeRejected
from test_anime_qb_e01_probe import SelectionQB, HASH, MAGNET


class SingleQB(SelectionQB):
    def __init__(self, size_mb):
        super().__init__(ready_after=0)
        self.single_size=size_mb*MB

    def torrent_files(self, infohash):
        files=super().torrent_files(infohash)
        for f in files:
            if f["index"]==0:
                f["size"]=self.single_size
            else:
                f["name"]="Season 02/attachment-%d.txt"%f["index"]
                f["size"]=1000
        return files


class SingleGateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path=Path(tmp.name)/"test.sqlite"
        initialize(self.db_path)
        self.db=sqlite3.connect(self.db_path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.event=receive(self.db,{"source":"autobrr",
            "source_guid":"single-e01","release_name":"Example Show S02E01",
            "info_hash":HASH,"tvdb_id":123,"anidb_id":456,
            "season":2,"episode":1,"magnet_uri":MAGNET})
        self.nid=self.event["notification_id"]

    def intake(self, qb):
        return admit_single_episode(self.db,self.nid,HASH,MAGNET,qb)

    def test_below_600_mb_starts_exactly_one_file(self):
        qb=SingleQB(500)
        self.assertEqual(self.intake(qb)["state"],"READY")
        self.assertEqual([qb.priorities[i] for i in range(12)],[1]+[0]*11)
        self.assertEqual(qb.start_calls,1)
        self.assertEqual(qb.adds,1)
        self.assertEqual(self.intake(qb)["state"],"READY")
        self.assertEqual(qb.adds,1)
        self.assertEqual(qb.start_calls,1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM anime_trial_size_reservations").fetchone()[0],1)

    def test_oversized_single_never_resumes_and_needs_review(self):
        qb=SingleQB(700)
        with self.assertLogs("anime_discovery.trial",level="WARNING") as logs:
            with self.assertRaises(TrialSizeRejected) as exc:
                self.intake(qb)
        self.assertEqual(exc.exception.reason,"EPISODE_SIZE_EXCEEDED")
        self.assertIn("action=NEEDS_REVIEW","\n".join(logs.output))
        self.assertEqual(qb.start_calls,0)
        self.assertEqual(qb.records[HASH]["state"],"pausedDL")
        self.assertEqual(qb.priority_calls,0)

    def test_prior_eligible_single_missing_first_episode_defers_before_qb(self):
        h="b"*40
        release=receive(self.db,{"source":"autobrr",
            "source_guid":"single-e02","release_name":"Example Show S02E02",
            "info_hash":h,"tvdb_id":123,"anidb_id":456,
            "season":2,"episode":2})
        qb=SingleQB(400)
        result=admit_single_episode(self.db,release["notification_id"],h,
            "magnet:?xt=urn:btih:"+h,qb)
        self.assertEqual(result["state"],"DEFERRED")
        self.assertEqual(qb.adds,0)


if __name__=="__main__":
    unittest.main()
