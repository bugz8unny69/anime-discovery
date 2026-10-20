"""Trial-window persistence, late Autobrr triggers and journal tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_trial_policy import record_verified_window,eligibility,window_for
from anime_webhook_processing import receive
from anime_shared_discovery import search_once

TVDB, ANIDB = 123,456


def event(ep, *, season=1, hashchar="a"):
    return {"source":"autobrr","source_guid":"event-%s-%s"%(season,ep),
            "release_name":"Example Show S%02dE%04d"%(season,ep),
            "info_hash":hashchar * 40,"tvdb_id":TVDB,"anidb_id":ANIDB,
            "season":season,"episode":ep}


def release(ep):
    h="%040x"%ep
    return {"title":"Example Show S01E%04d"%ep,
            "magnetUrl":"magnet:?xt=urn:btih:"+h,"seeders":ep+2}


class FakeClient:
    def __init__(self, releases):
        self.releases=releases
        self.queries=[]
    def search(self, title):
        self.queries.append(title)
        return self.releases


class TrialPolicyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path=Path(temp.name)/"test.sqlite"
        initialize(path)
        self.db=sqlite3.connect(path,isolation_level=None)
        self.addCleanup(self.db.close)

    def test_unconfigured_new_season_only_01_to_06(self):
        self.assertEqual(window_for(self.db,tvdb_id=TVDB,anidb_id=ANIDB,
                                    season=2)["start"],1)
        self.assertTrue(eligibility(self.db,tvdb_id=TVDB,anidb_id=ANIDB,
                                    season=2,episode=1)["eligible"])
        self.assertFalse(eligibility(self.db,tvdb_id=TVDB,anidb_id=ANIDB,
                                     season=2,episode=7)["eligible"])

    def test_episode_12_is_excluded_and_upstream_only_backfills_first_six(self):
        with self.assertLogs("anime_discovery.trial",level="INFO") as logs:
            result=receive(self.db,event(12),gap_search_enabled=True)
        self.assertTrue(result["excluded"])
        self.assertFalse(result["queued"])
        self.assertIn("event=TRIGGER_SKIPPED", "\n".join(logs.output))
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT status FROM notifications").fetchone()[0],
                         "EXCLUDED_TRIAL_WINDOW")
        self.assertEqual(self.db.execute("""SELECT count(*) FROM daemon_jobs
            WHERE kind='series_gap_search'""").fetchone()[0],1)
        request={"title":"Example Show","tvdb_id":str(TVDB),"anidb_id":str(ANIDB),
                 "season":1,"up_to":12,"origin":"autobrr"}
        search=search_once(self.db,request,FakeClient([release(n) for n in range(1,13)]))
        self.assertEqual(search["queued"],6)
        episodes=self.db.execute("SELECT episode FROM episode_dispatch ORDER BY episode").fetchall()
        self.assertEqual(episodes,[(n,) for n in range(1,7)])

    def test_episode_seven_triggers_backfill_but_is_never_approved(self):
        result=receive(self.db,event(7),gap_search_enabled=True)
        self.assertTrue(result["excluded"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],0)
        from anime_webhook_processing import approve
        with self.assertRaisesRegex(ValueError,"outside verified trial"):
            approve(self.db,result["notification_id"],
                    {"tvdb_id":TVDB,"anidb_id":ANIDB,"season":1,"episode":7})

    def test_verified_ongoing_1001_window_is_immutable(self):
        params=dict(tvdb_id=TVDB,anidb_id=ANIDB,season=1,unit_key="ongoing:1001",
                    mode="ONGOING",start_episode=1001,
                    evidence_ref="tvdb:123:ongoing:1001")
        with self.assertLogs("anime_discovery.trial",level="INFO") as logs:
            first=record_verified_window(self.db,**params)
        self.assertEqual(first["end"],1006)
        self.assertIn("event=WINDOW_LOCKED", "\n".join(logs.output))
        record_verified_window(self.db,**params)
        self.assertTrue(eligibility(self.db,tvdb_id=TVDB,anidb_id=ANIDB,
                                    season=1,episode=1001)["eligible"])
        self.assertFalse(eligibility(self.db,tvdb_id=TVDB,anidb_id=ANIDB,
                                     season=1,episode=999)["eligible"])
        self.assertTrue(receive(self.db,event(1001))["queued"])
        self.assertTrue(receive(self.db,event(1007))["excluded"])
        with self.assertRaisesRegex(ValueError,"conflicting boundary"):
            record_verified_window(self.db,**{**params,"start_episode":1002})
        self.assertEqual(self.db.execute("SELECT count(*) FROM anime_trial_windows").fetchone()[0],1)

    def test_verified_part_two_13_to_18_not_old_part_one(self):
        record_verified_window(self.db,tvdb_id=TVDB,anidb_id=ANIDB,season=1,
                               unit_key="part:2",mode="PART",start_episode=13,
                               evidence_ref="tvdb:123:cour:2")
        self.assertTrue(receive(self.db,event(13))["queued"])
        self.assertTrue(receive(self.db,event(12))["excluded"])
        self.assertTrue(receive(self.db,event(19))["excluded"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],1)

    def test_ambiguous_multiple_parts_do_not_select_one_by_guessing(self):
        record_verified_window(self.db,tvdb_id=TVDB,anidb_id=ANIDB,season=1,
                               unit_key="part:1",mode="PART",start_episode=1,
                               evidence_ref="tvdb:123:cour:1")
        record_verified_window(self.db,tvdb_id=TVDB,anidb_id=ANIDB,season=1,
                               unit_key="part:2",mode="PART",start_episode=13,
                               evidence_ref="tvdb:123:cour:2")
        with self.assertRaisesRegex(ValueError,"Ambiguous"):
            eligibility(self.db,tvdb_id=TVDB,anidb_id=ANIDB,season=1,episode=13)

    def test_no_boundary_from_filename_or_unverified_auto_mode(self):
        self.assertTrue(receive(self.db,event(1001))["excluded"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM anime_trial_windows").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
