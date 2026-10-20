"""Unified intake identity triage and delayed NTFY review tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_unified_identity_monitor import check_once
from anime_ntfy_monitor import check_once as alerts

class TriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"db.sqlite"
        initialize(self.path)
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.nid=self.db.execute("""INSERT INTO notifications
          (source,release_name,source_guid,info_hash,received_at,status)
          VALUES ('nyaa','[Group] Test - 02','triage','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1,'IDENTIFYING')""").lastrowid
        self.settings={"ntfy":{"enabled":True,"reminder_hours":1}}
        self.notified=[]
        self.sender=lambda s,k,n,t:self.notified.append(n) or True

    def test_review_only_after_lookup_and_one_alert(self):
        self.assertEqual(alerts(self.db,self.settings,{},now=1000,sender=self.sender)["sent"],0)
        self.assertEqual(check_once(self.db,{}, {},now=1001,
            probe=lambda *args:{"decision":"NEEDS_REVIEW","issues":["UNVERIFIED"]})["processed"],1)
        self.assertEqual(self.db.execute("SELECT status FROM notifications WHERE id=?",
            (self.nid,)).fetchone()[0],"NEEDS_REVIEW")
        self.assertEqual(alerts(self.db,self.settings,{},now=1002,sender=self.sender)["sent"],1)
        self.assertEqual(alerts(self.db,self.settings,{},now=1003,sender=self.sender)["sent"],0)
        self.assertEqual(self.notified,[self.nid])
        self.assertIsNone(self.db.execute("SELECT 1 FROM daemon_jobs WHERE subject_key=?",
            (str(self.nid),)).fetchone())

    def test_transient_provider_failure_retries_before_alert(self):
        def broken(*args):raise TimeoutError("Do not log details")
        for attempt,now in enumerate((1000,1200,1600),1):
            self.assertEqual(check_once(self.db,{}, {},now=now,probe=broken)["processed"],1)
            status=self.db.execute("SELECT status FROM notifications WHERE id=?",
                (self.nid,)).fetchone()[0]
            self.assertEqual(status,"IDENTIFYING" if attempt<3 else "NEEDS_REVIEW")
        self.assertEqual(alerts(self.db,self.settings,{},now=2000,sender=self.sender)["sent"],1)
        self.assertEqual(self.db.execute("SELECT attempts FROM unified_identity_checks").fetchone()[0],3)

    def test_verified_episode_mapping_queues_only_once(self):
        from anime_dashboard_queries import all_jobs
        report={"decision":"AUTO_VERIFIED","issues":[],
                "approval":{"tvdb_id":123,"anidb_id":456,"season":1,"episode":2},
                "verified_anidb_episode_id":9876}
        result=check_once(self.db,{}, {},now=1000,probe=lambda *_:report)
        self.assertEqual(result["processed"],1)
        self.assertEqual(self.db.execute("SELECT status FROM notifications").fetchone()[0],"APPROVED")
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],1)
        self.assertEqual(alerts(self.db,self.settings,{},now=1001,sender=self.sender)["sent"],0)
        self.assertEqual(check_once(self.db,{}, {},now=1002,probe=lambda *_:report)["processed"],0)

    def test_public_titles_crossref_requires_exact_verified_episode_map(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import investigate
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{
            "123:1:2":{"anidb_episode_id":9876,"verified":True}}}}
        secrets={"tvdb_api_key":"secret-never-in-report"}
        anidb=[{"anidb_id":"456","titles":["Example"],"matched_titles":["Example"]}]
        def fetch(url,bearer=None):
            self.assertEqual(bearer,"session")
            if "/extended" in url:
                return {"data":{"id":123,"remoteIds":[
                    {"sourceName":"AniDB","id":"456"}]}}
            return {"data":{"episodes":[{"id":777,"seasonNumber":1,"number":2}]},
                    "links":{"next":None}}
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=(anidb,False)):
            result=investigate("[Group] Example - 02",settings,secrets,None,
                search=lambda aliases,key:([{"tvdb_id":"123","name":"Example"}],[]),
                login=lambda key:"session",fetch=fetch)
            self.assertEqual(result["decision"],"AUTO_VERIFIED")
            self.assertEqual(result["approval"]["episode"],2)
            self.assertNotIn("secret-never-in-report",str(result))
            settings["identity"]["episode_map"]={}
            missing=investigate("[Group] Example - 02",settings,secrets,None,
                search=lambda aliases,key:([{"tvdb_id":"123","name":"Example"}],[]),
                login=lambda key:"session",fetch=fetch)
            self.assertEqual(missing["decision"],
                             "SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED")
            self.assertNotIn("approval",missing)

    def test_live_action_collision_rejected_and_remote_ids_diagnosed(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import investigate
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}}
        rows=[{"anidb_id":"456","titles":["Solo Leveling"],
               "matched_titles":["Solo Leveling"]}]
        candidates=[{"tvdb_id":"389597","name":"Solo Leveling"},
                    {"tvdb_id":"465668","name":"Solo Leveling"}]
        def fetch(url,bearer=None):
            if "/389597/" in url:
                return {"data":{"id":389597,"genres":[{"name":"Animation"}],
                                "remoteIds":[{"sourceName":"AniDB","id":"456"}]}}
            return {"data":{"id":465668,"seriesType":{"name":"Live Action"},
                            "remoteIds":[{"sourceName":"AniDB","id":"456"}]}}
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=(rows,False)):
            result=investigate("[Group] Solo Leveling - 01",settings,
                {"tvdb_api_key":"hidden"},None,
                search=lambda *_:(candidates,[]),login=lambda _:"token",fetch=fetch)
        self.assertEqual(result["matching_pairs"],
                         [{"tvdb_id":"389597","anidb_id":"456"}])
        diagnostics={r["tvdb_id"]:r for r in result["crossref_diagnostics"]}
        self.assertEqual(diagnostics["465668"]["reason"],
                         "REJECTED_UNSUITABLE_TVDB_MEDIA_TYPE")
        self.assertEqual(diagnostics["389597"]["matching_anidb_ids"],["456"])
        self.assertNotIn("approval",result)

    def test_title_threshold_rejects_low_score_even_with_crossref(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import investigate
        settings={"tvdb":{"enabled":True},"identity":{"match_threshold_pct":90,
            "episode_map":{"123:1:2":{"anidb_episode_id":9876,"verified":True}}}}
        rows=[{"anidb_id":"456","titles":["Example"],"matched_titles":["Example"]}]
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(rows,False)):
            def query(aliases,key):
                return ([{"tvdb_id":"123","name":"Totally Different Show"}],[])
            result=investigate("[Group] Example - 02",settings,{"tvdb_api_key":"hidden"},None,
                search=query,login=lambda key:"session",fetch=lambda *a,**k:self.fail("Should not fetch rejected title"))
        self.assertEqual(result["decision"],"NEEDS_REVIEW")
        self.assertIn("ALL_TVDB_TITLES_BELOW_THRESHOLD",result["issues"])
        self.assertFalse(result["candidate_scores"][0]["passed"])
        self.assertEqual(result["candidate_scores"][0]["threshold_pct"],90)
        self.assertNotIn("hidden",str(result))

    def test_historical_untrusted_enters_identity_triage_before_ntfy(self):
        other=self.db.execute("""INSERT INTO notifications
            (source,release_name,source_guid,info_hash,received_at)
            VALUES ('nyaa','Historical unknown','old-guid',?,1)""",
            ("b"*40,)).lastrowid
        self.assertEqual(alerts(self.db,self.settings,{},now=500,sender=self.sender)["sent"],0)
        check_once(self.db,{}, {},now=501,limit=2,
            probe=lambda *_:{"decision":"NEEDS_REVIEW","issues":["UNVERIFIED"]})
        self.assertEqual(self.db.execute("SELECT status FROM notifications WHERE id=?",
            (other,)).fetchone()[0],"NEEDS_REVIEW")
        self.assertEqual(alerts(self.db,self.settings,{},now=502,sender=self.sender)["sent"],2)

    def test_disabled_public_anidb_does_not_require_a_cache_or_api_key(self):
        config={"anidb":{"enabled":False}}
        result=check_once(self.db,config,{},now=600)
        self.assertEqual(result["processed"],1)
        self.assertEqual(self.db.execute("SELECT status FROM notifications").fetchone()[0],
                         "NEEDS_REVIEW")

    def test_unique_verified_series_still_requires_episode_mapping(self):
        self.assertEqual(check_once(self.db,{}, {},now=2000,probe=lambda *_:{
            "decision":"SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED",
            "matching_pairs":[{"tvdb_id":"123","anidb_id":"456"}],
            "issues":[]})["processed"],1)
        self.assertEqual(self.db.execute("SELECT status FROM notifications").fetchone()[0],"NEEDS_REVIEW")

if __name__=="__main__":unittest.main()
