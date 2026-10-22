"""Unified intake identity triage and delayed NTFY review tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_unified_identity_monitor import check_once, investigate
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

    def test_anidb_candidate_evidence_preserves_titles(self):
        from anime_unified_identity_monitor import investigate
        from unittest.mock import patch
        settings={"identity":{"match_threshold_pct":90},
                  "anidb":{"enabled":True},"tvdb":{"enabled":False}}
        rows=[{"anidb_id":"11905","matched_titles":["Saga of Tanya the Evil"],
               "titles":["Saga of Tanya the Evil","Youjo Senki"]}]
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(rows,False)):
            evidence=investigate("Saga of Tanya the Evil - 07",settings,{},Path("unused"))
        self.assertEqual(evidence["anidb_candidates"],[{
            "anidb_id":"11905","matched_titles":["Saga of Tanya the Evil"],
            "titles":["Saga of Tanya the Evil","Youjo Senki"]}])
        self.assertIn("TVDB_DISABLED_OR_KEY_MISSING",evidence["issues"])

    def test_batch_and_special_have_actionable_review_reasons(self):
        # No remote sources or database mutation; actual incident-style names.
        catalog=Path(self.tmp.name)/"titles.xml"
        catalog.write_text("<animetitles></animetitles>",encoding="utf-8")
        settings={"identity":{},"anidb":{"enabled":True},"tvdb":{"enabled":False}}
        batch=investigate(
            "[Trix] Cyberpunk Edgerunners S02 1080p NF WEB-DL "
            "Opus2.0 AV1 (Dual-Audio, Multi-Subs) (Season S2) (Batch)",
            settings,{},catalog)
        self.assertEqual(batch["release_scope_hint"]["season_hint"],2)
        self.assertIn("BATCH_FILE_MANIFEST_REQUIRED",batch["issues"])
        self.assertNotEqual(batch["decision"],"AUTO_VERIFIED")
        special=investigate(
            "[Anime Time] KonoSuba - God's Blessing On This "
            "Wonderful World - S00E05 - Movie Legend Of Crimson "
            "(Fixed Subs Fonts) [BD] [Dual Audio][1080p]",
            settings,{},catalog)
        self.assertIn("SEASON_ZERO_SPECIAL_OUTSIDE_TRIAL_SCOPE",special["issues"])
        self.assertNotEqual(special["decision"],"AUTO_VERIFIED")

    def test_invalid_xml_is_metadata_retry_not_user_review_even_after_three_attempts(self):
        import xml.etree.ElementTree as ET
        def malformed(*args):
            raise ET.ParseError("Malformed upstream XML")
        for moment in (1000,1500,3000,5000):
            self.assertEqual(check_once(self.db,{}, {},now=moment,probe=malformed)["processed"],1)
            record=self.db.execute("""SELECT decision,next_at,evidence_json
                FROM unified_identity_checks WHERE notification_id=?""",(self.nid,)).fetchone()
            self.assertEqual(record[0],"LOOKUP_RETRY")
            self.assertGreater(record[1],moment)
            self.assertIn("METADATA_UNAVAILABLE_IDENTITY_RESOLUTION",record[2])
            self.assertEqual(self.db.execute("SELECT status FROM notifications WHERE id=?",
                (self.nid,)).fetchone()[0],"IDENTIFYING")
            self.assertEqual(alerts(self.db,self.settings,{},now=moment+1,
                                    sender=self.sender)["sent"],0)
        self.assertEqual(self.notified,[])

    def test_metadata_sources_are_stage_labeled_and_retry(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import MetadataUnavailable
        with patch("anime_unified_identity_monitor.ensure_titles",
                   side_effect=MetadataUnavailable("ANIDB_TITLES")):
            result=check_once(self.db,{"daemon":{"database_path":str(self.path)}}, {},
                              now=1000)
        self.assertEqual(result["pending_retries"],1)
        row=self.db.execute("SELECT evidence_json FROM unified_identity_checks").fetchone()
        self.assertIn("METADATA_UNAVAILABLE_ANIDB_TITLES",row[0])

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

    def test_verified_episode_ten_excluded_without_automatic_backfill(self):
        import json
        report={"decision":"AUTO_VERIFIED","issues":[],
                "title_queries":["Example Show"],
                "approval":{"tvdb_id":123,"anidb_id":456,"season":1,"episode":10},
                "verified_anidb_episode_id":9876}
        settings={"prowlarr":{"enabled":True}}
        result=check_once(self.db,settings,{},now=1000,probe=lambda *_:report.copy())
        self.assertEqual(result["processed"],1)
        self.assertEqual(result["pending_retries"],0)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "EXCLUDED_TRIAL_WINDOW")
        self.assertEqual(self.db.execute(
            "SELECT decision FROM unified_identity_checks WHERE notification_id=?",
            (self.nid,)).fetchone()[0],"EPISODE_EXCLUDED")
        jobs=self.db.execute(
            "SELECT kind,payload_json FROM daemon_jobs").fetchall()
        self.assertEqual(jobs,[])
        self.assertEqual(check_once(self.db,settings,{},now=1300,
            probe=lambda *_:report.copy())["processed"],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs").fetchone()[0],0)

    def test_excluded_episode_without_configured_search_does_not_retry(self):
        report={"decision":"AUTO_VERIFIED","issues":[],
                "title_queries":["Example Show"],
                "approval":{"tvdb_id":123,"anidb_id":456,"season":2,"episode":12},
                "verified_anidb_episode_id":9876}
        self.assertEqual(check_once(self.db,{}, {},now=1000,
            probe=lambda *_:report.copy())["pending_retries"],0)
        self.assertEqual(self.db.execute(
            "SELECT decision FROM unified_identity_checks").fetchone()[0],
            "EPISODE_EXCLUDED")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs").fetchone()[0],0)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications").fetchone()[0],"EXCLUDED_TRIAL_WINDOW")

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

    def test_auto_verified_handoff_passes_real_acquisition_gate(self):
        from anime_acquisition_gate import approved_dispatch
        from anime_identity_rejection_gate import resolve_notification
        report={"decision":"AUTO_VERIFIED","issues":[],
                "approval":{"tvdb_id":123,"anidb_id":456,"season":1,"episode":2},
                "verified_anidb_episode_id":9876}
        self.assertEqual(check_once(self.db,{}, {},now=1000,
                         probe=lambda *_:report)["processed"],1)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "APPROVED")
        self.assertEqual(resolve_notification(self.db,self.nid),
                         self.db.execute("SELECT id FROM series").fetchone()[0])
        self.assertEqual(approved_dispatch(self.db,self.nid)["episode"],2)
        job=self.db.execute("""SELECT state FROM daemon_jobs WHERE
            kind='claimed_acquisition' AND subject_key=?""",(str(self.nid),)).fetchone()
        self.assertEqual(job,("READY",))

    def test_pre_acquisition_proof_is_saved_before_queueing_for_keep(self):
        report={"decision":"AUTO_VERIFIED","issues":[],
                "approval":{"tvdb_id":123,"anidb_id":456,"season":2,"episode":3},
                "episode_mapping":{"anidb_episode_number":2,"tvdb_season":2,"tvdb_episode":3},
                "verified_anidb_episode_id":9876,
                "episode_id_source":"AniDB HTTP catalog"}
        self.assertEqual(check_once(self.db,{}, {},now=1200,
            probe=lambda *_: report)["processed"],1)
        self.assertEqual(self.db.execute("""SELECT anidb_id,anidb_episode_number,
            anidb_episode_id,source FROM verified_anidb_episode_ids""").fetchone(),
            (456,2,9876,"AniDB HTTP catalog"))
        self.assertEqual(self.db.execute(
            "SELECT status FROM series").fetchone()[0],"DISCOVERED")
        self.assertIsNone(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='sonarr_keep'").fetchone())

    def test_shared_anidb_rate_limit_waits_without_review_alert(self):
        from anime_anidb_episode_lookup import AniDBLookupDeferred
        def deferred(*_):
            raise AniDBLookupDeferred(12)
        result=check_once(self.db,{}, {},now=1000,probe=deferred)
        self.assertEqual(result["pending_retries"],1)
        check=self.db.execute("SELECT attempts,next_at,decision FROM unified_identity_checks").fetchone()
        self.assertEqual(check,(0,1013,"LOOKUP_RETRY"))
        self.assertEqual(self.db.execute("SELECT status FROM notifications").fetchone()[0],
                         "IDENTIFYING")
        self.assertEqual(alerts(self.db,self.settings,{},now=1010,sender=self.sender)["sent"],0)

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
            self.assertEqual(result["decision"],"NEEDS_REVIEW")
            self.assertIn("SEASON_EPISODE_MAPPING_UNVERIFIED",result["issues"])
            self.assertNotIn("approval",result)
            self.assertNotIn("secret-never-in-report",str(result))
            settings["identity"]["episode_map"]={}
            missing=investigate("[Group] Example - 02",settings,secrets,None,
                search=lambda aliases,key:([{"tvdb_id":"123","name":"Example"}],[]),
                login=lambda key:"session",fetch=fetch)
            self.assertEqual(missing["decision"],"NEEDS_REVIEW")
            self.assertIn("SEASON_EPISODE_MAPPING_UNVERIFIED",missing["issues"])
            self.assertNotIn("approval",missing)

    def test_missing_anime_lists_rule_never_infers_season_one_or_episode(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import investigate
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{
            "123:1:19":{"verified":True,"anidb_episode_id":9876}}}}
        rows=[{"anidb_id":"456","titles":["Example"],"matched_titles":["Example"]}]
        xml=b'<anime-list><anime anidbid="456" tvdbid="123"/></anime-list>'
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":123,"remoteIds":[{"sourceName":"AniDB","id":"456"}]}}
            self.fail("No TVDB episode lookup allowed without a verified episode rule")
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(rows,False)):
            for name in ("[Group] Example S01E19","[Group] Example S02E19",
                         "[Group] Example S04E19","[Group] Example - 19"):
                with self.subTest(release=name):
                    report=investigate(name,settings,{"tvdb_api_key":"private"},None,
                        mapping_xml=xml,search=lambda *_:([{"tvdb_id":"123","name":"Example"}],[]),
                        login=lambda _:"token",fetch=fetch)
                    self.assertEqual(report["decision"],"NEEDS_REVIEW")
                    self.assertIn("SEASON_EPISODE_MAPPING_UNVERIFIED",report["issues"])
                    self.assertIsNone(report["episode_mapping"])
                    self.assertNotIn("approval",report)
                    self.assertNotIn("private",str(report))

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

    def test_season_candidate_discovery_finds_distinct_sequel_anidb_id(self):
        from anime_season_candidate_discovery import season_candidates
        from anime_unified_identity_monitor import investigate
        from unittest.mock import patch
        catalog=Path(self.tmp.name)/"titles.xml"
        catalog.write_text("""<animetitles>
            <anime aid="11370"><title>ReZERO</title></anime>
            <anime aid="19242"><title>ReZERO Fourth Season</title></anime>
            </animetitles>""")
        xml=(b'<anime-list>'
             b'<anime anidbid="11370" tvdbid="305089" defaulttvdbseason="1"/>'
             b'<anime anidbid="19242" tvdbid="305089" defaulttvdbseason="4"/>'
             b'</anime-list>')
        discovered=season_candidates(xml,catalog,"305089",4,19)
        self.assertEqual([d["anidb_id"] for d in discovered],["19242"])
        self.assertEqual(discovered[0]["episode_rule"]["tvdb_episode"],19)
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}}
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":305089,"name":"ReZERO",
                                "genres":[{"name":"Animation"}],
                                "remoteIds":[{"sourceName":"AniDB","id":"11370"}]}}
            return {"data":{"episodes":[{"id":888,"seasonNumber":4,"number":19}]},
                    "links":{"next":None}}
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=([{"anidb_id":"11370","titles":["ReZERO"],
                                  "matched_titles":["ReZERO"]}],False)):
            result=investigate("[Group] ReZERO S04E19",settings,
                {"tvdb_api_key":"test"},catalog,mapping_xml=xml,
                search=lambda *_:([{"tvdb_id":"305089","name":"ReZERO"}],[]),
                login=lambda _:"token",fetch=fetch)
        self.assertEqual(result["decision"],"SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED")
        self.assertIn("VERIFIED_EPISODE_MAPPING_MISSING",result["issues"])
        self.assertIn("19242",[v["anidb_id"] for v in result["season_mapping_candidates"]])
        self.assertNotIn("approval",result)

    def test_anidb_first_sequel_uses_targeted_tvdb_and_exact_eid(self):
        from anime_unified_identity_monitor import investigate
        from unittest.mock import patch
        catalog=Path(self.tmp.name)/"titles.xml"
        catalog.write_text("""<animetitles>
        <anime aid="11370"><title>ReZERO</title></anime>
        <anime aid="19242"><title>ReZERO Fourth Season</title></anime>
        </animetitles>""")
        xml=(b'<anime-list>'
             b'<anime anidbid="11370" tvdbid="305089" defaulttvdbseason="1"/>'
             b'<anime anidbid="19242" tvdbid="305089" defaulttvdbseason="4"/>'
             b'</anime-list>')
        calls=[]
        def fetch(url,bearer=None):
            calls.append(url)
            if "/extended" in url:
                return {"data":{"id":305089,"name":"ReZERO",
                        "genres":[{"name":"Animation"}],
                        "remoteIds":[{"sourceName":"AniDB","id":"11370"}]}}
            return {"data":{"episodes":[{"id":888,"seasonNumber":4,"number":19}]},
                    "links":{"next":None}}
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(
                [{"anidb_id":"11370","titles":["ReZERO"],
                  "matched_titles":["ReZERO"]}],False)):
            params=dict(settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}},
                secrets={"tvdb_api_key":"secret"},catalog=catalog,
                mapping_xml=xml,search=lambda *_:self.fail("Broad TVDB search forbidden"),
                login=lambda _:"token",fetch=fetch)
            pending=investigate("[Group] ReZERO S04E19",anidb_resolve=None,**params)
            verified=investigate("[Group] ReZERO S04E19",
                anidb_resolve=lambda aid,ep:77777 if (aid,ep)==(19242,19) else None,
                **params)
        self.assertEqual(pending["decision"],
                         "SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED")
        self.assertEqual(verified["decision"],"AUTO_VERIFIED")
        self.assertEqual(verified["approval"],
                         {"tvdb_id":305089,"anidb_id":19242,"season":4,"episode":19})
        self.assertEqual(verified["verified_anidb_episode_id"],77777)
        self.assertEqual(verified["episode_id_source"],"AniDB HTTP catalog")
        self.assertEqual(len([c for c in calls if "/extended" in c]),2)

    def test_season_selection_ambiguous_entries_fail_closed(self):
        from anime_unified_identity_monitor import investigate
        from unittest.mock import patch
        catalog=Path(self.tmp.name)/"titles.xml"
        catalog.write_text("""<animetitles>
          <anime aid="111"><title>Example</title></anime>
          <anime aid="222"><title>Example Second</title></anime>
          <anime aid="333"><title>Example Another</title></anime></animetitles>""")
        xml=(b'<anime-list><anime anidbid="111" tvdbid="123" defaulttvdbseason="1"/>'
             b'<anime anidbid="222" tvdbid="123" defaulttvdbseason="2"/>'
             b'<anime anidbid="333" tvdbid="123" defaulttvdbseason="2"/></anime-list>')
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(
                [{"anidb_id":"111","titles":["Example"],"matched_titles":["Example"]}],False)):
            report=investigate("[Group] Example S02E03",
                {"tvdb":{"enabled":True},"identity":{"episode_map":{}}},
                {"tvdb_api_key":"key"},catalog,mapping_xml=xml,
                search=lambda *_:self.fail("No broad search"),
                login=lambda _:"token",
                fetch=lambda url,bearer=None:{"data":{"id":123,"name":"Example",
                    "genres":[{"name":"Animation"}]}})
        self.assertEqual(report["decision"],"NEEDS_REVIEW")
        self.assertIn("AMBIGUOUS_SEASON_SPECIFIC_ANIDB",report["issues"])
        self.assertNotIn("approval",report)

    def test_reverse_mapping_without_offset_preserves_episode_number(self):
        from anime_identity_mapping_v4 import resolve_tvdb_episode
        xml=(b'<anime-list><anime anidbid="789" tvdbid="123" '
             b'defaulttvdbseason="2"/></anime-list>')
        rule=resolve_tvdb_episode(xml,"789","123",2,3)
        self.assertIsNotNone(rule)
        self.assertEqual(rule["anidb_episode_number"],3)
        self.assertEqual(rule["tvdb_episode"],3)

    def test_reverse_mapping_offset_resolves_anidb_number_not_tvdb_number(self):
        from anime_identity_mapping_v4 import resolve_tvdb_episode
        xml=(b'<anime-list><anime anidbid="456" tvdbid="123" '
             b'defaulttvdbseason="2" episodeoffset="2"/></anime-list>')
        result=resolve_tvdb_episode(xml,"456","123",2,3)
        self.assertEqual(result["anidb_episode_number"],1)
        self.assertEqual(result["tvdb_episode"],3)
        self.assertIsNone(resolve_tvdb_episode(xml,"456","123",1,3))

    def test_offset_episode_pipeline_uses_actual_anidb_episode_number(self):
        from anime_unified_identity_monitor import investigate
        from unittest.mock import patch
        xml=(b'<anime-list><anime anidbid="456" tvdbid="123" '
             b'defaulttvdbseason="2" episodeoffset="2"/></anime-list>')
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}}
        rows=[{"anidb_id":"456","titles":["Example"],"matched_titles":["Example"]}]
        called=[]
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":123,"name":"Example",
                                "genres":[{"name":"Animation"}]}}
            return {"data":{"episodes":[{"id":777,"seasonNumber":2,"number":3}]},
                    "links":{"next":None}}
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(rows,False)):
            result=investigate("[Group] Example S02E03",settings,
                {"tvdb_api_key":"secret"},None,mapping_xml=xml,
                search=lambda *_:self.fail("Expected targeted TVDB lookup"),
                login=lambda _:"token",fetch=fetch,
                anidb_resolve=lambda aid,ep:(called.append((aid,ep)) or
                    (9876 if (aid,ep)==(456,1) else None)))
        self.assertEqual(called,[(456,1)])
        self.assertEqual(result["decision"],"AUTO_VERIFIED")
        self.assertEqual(result["verified_anidb_episode_id"],9876)
        self.assertEqual(result["episode_mapping"]["anidb_episode_number"],1)

    def test_anidb_first_release_shapes_keep_single_and_batch_paths_separate(self):
        from anime_unified_identity_monitor import investigate
        from anime_batch_selection import release_scope_hint
        from anime_identification_probe import release_title
        from unittest.mock import patch
        catalog=Path(self.tmp.name)/"shapes-titles.xml"
        catalog.write_text('<animetitles><anime aid="456"><title>Example</title></anime>'
                           '<anime aid="789"><title>Example Second Season</title></anime>'
                           '</animetitles>')
        xml=(b'<anime-list><anime anidbid="456" tvdbid="123" '
             b'defaulttvdbseason="1"/><anime anidbid="789" '
             b'tvdbid="123" defaulttvdbseason="2"/></anime-list>')
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}}
        secrets={"tvdb_api_key":"hidden"}
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":123,"name":"Example",
                        "genres":[{"name":"Animation"}],
                        "remoteIds":[{"sourceName":"AniDB","id":"456"}]}}
            return {"data":{"episodes":[
                {"id":888,"seasonNumber":1,"number":1},
                {"id":889,"seasonNumber":2,"number":1}]},
                "links":{"next":None}}
        base={"search":lambda *_:self.fail("Targeted lookup should avoid broad search"),
              "login":lambda _:"token","fetch":fetch,"mapping_xml":xml,
              "anidb_resolve":lambda aid,ep:9876 if (aid,ep)==(789,1) else None}
        with patch("anime_unified_identity_monitor.anidb_matches",
                   return_value=([{"anidb_id":"456","titles":["Example"],
                                  "matched_titles":["Example"]}],False)):
            plain=investigate("[Group] Example - 01",settings,secrets,catalog,**base)
            season_two=investigate("[Group] Example S02E01",settings,secrets,catalog,**base)
            batch=investigate("[Group] Example S02 (Batch)",settings,secrets,catalog,**base)
            season_only=investigate("[Group] Example Season 2",settings,secrets,catalog,**base)

        # An unqualified E01 is not silently interpreted as season 1.
        self.assertEqual(release_scope_hint("[Group] Example - 01")["kind"],"unknown")
        self.assertEqual(plain["episode_candidate"],1)
        self.assertNotEqual(plain["decision"],"AUTO_VERIFIED")
        self.assertNotIn("approval",plain)
        # A season-qualified single episode can resolve the exact AniDB EID.
        self.assertEqual(season_two["release_scope_hint"]["kind"],"single_episode")
        self.assertEqual(season_two["decision"],"AUTO_VERIFIED")
        self.assertEqual(season_two["approval"]["season"],2)
        self.assertEqual(season_two["approval"]["anidb_id"],789)
        self.assertEqual(season_two["verified_anidb_episode_id"],9876)
        # A season pack has no episode and must preserve the original verified
        # identity anchor for the separately gated batch-manifest handler.
        for name,report in (("[Group] Example S02 (Batch)",batch),
                            ("[Group] Example Season 2",season_only)):
            with self.subTest(release=name):
                self.assertEqual(release_scope_hint(name)["kind"],"season_pack")
                self.assertIsNone(release_title(name)[1])
                self.assertIsNone(report["episode_candidate"])
                self.assertEqual(report["decision"],"NEEDS_REVIEW")
                self.assertIn("BATCH_FILE_MANIFEST_REQUIRED",report["issues"])
                self.assertIn("EPISODE_NUMBER_UNRESOLVED",report["issues"])
                self.assertEqual(report["matching_pairs"],
                                 [{"tvdb_id":"123","anidb_id":"456"}])
                self.assertNotIn("approval",report)
                self.assertEqual(report["season_mapping_candidates"],[])

    def test_anime_lists_and_direct_anidb_episode_enable_verification(self):
        from unittest.mock import patch
        from anime_unified_identity_monitor import investigate
        xml=b'<anime-list><anime anidbid="456" tvdbid="123" defaulttvdbseason="2" episodeoffset="1"/></anime-list>'
        settings={"tvdb":{"enabled":True},"identity":{"episode_map":{}}}
        rows=[{"anidb_id":"456","titles":["Example"],"matched_titles":["Example"]}]
        def fetch(url,bearer=None):
            if "/extended" in url:
                return {"data":{"id":123,"genres":[{"name":"Animation"}],
                                "remoteIds":[]}}
            return {"data":{"episodes":[{"id":777,"seasonNumber":2,"number":3}]},
                    "links":{"next":None}}
        with patch("anime_unified_identity_monitor.anidb_matches",return_value=(rows,False)):
            kwargs=dict(search=lambda *_:([{"tvdb_id":"123","name":"Example"}],[]),
                login=lambda _:"token",fetch=fetch,mapping_xml=xml)
            missing=investigate("[Group] Example - 02",settings,{"tvdb_api_key":"key"},None,**kwargs)
            self.assertEqual(missing["decision"],
                             "SERIES_LINK_VERIFIED_EPISODE_MAPPING_REQUIRED")
            self.assertNotIn("approval",missing)
            resolved=investigate("[Group] Example - 02",settings,{"tvdb_api_key":"key"},None,
                anidb_resolve=lambda aid,epno: 9876 if (aid,epno)==(456,2) else None,
                **kwargs)
        self.assertEqual(resolved["decision"],"AUTO_VERIFIED")
        self.assertEqual(resolved["approval"],
                         {"tvdb_id":123,"anidb_id":456,"season":2,"episode":3})
        self.assertEqual(resolved["verified_anidb_episode_id"],9876)

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
