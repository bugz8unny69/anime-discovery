"""Identity monitor pack handoff never accepts a release title as ID proof."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_fresh_database import initialize
from anime_webhook_processing import receive
from anime_unified_identity_monitor import check_once
from test_anime_batch_worker import XML, REPORT, SETTINGS, HASH, MAGNET, RELEASE


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.db_path=self.dir/"db.sqlite"
        initialize(self.db_path)
        self.db=sqlite3.connect(self.db_path,isolation_level=None)
        self.addCleanup(self.db.close)
        packet=receive(self.db,{"source":"autobrr","source_guid":"batch-handoff",
            "release_name":RELEASE,"info_hash":HASH,"magnet_uri":MAGNET})
        self.nid=packet["notification_id"]
        self.settings={"identity":SETTINGS["identity"],
                       "anidb":{"enabled":True,"client":""},
                       "daemon":{"database_path":str(self.db_path)},
                       "tvdb":{"enabled":True}}
        (self.dir/"anime-lists.xml").write_bytes(XML)

    def run_identity(self, report):
        with patch("anime_unified_identity_monitor.ensure_titles",
                   return_value=self.dir/"anidb-titles.xml"),patch(
                   "anime_unified_identity_monitor.ensure_anime_lists",
                   return_value=XML),patch(
                   "anime_unified_identity_monitor.investigate",
                   return_value=report):
            return check_once(self.db,self.settings,{},now=2000)

    def test_indexer_label_does_not_override_authenticated_batch_intake(self):
        for label in ("nyaa","AnimePlease"):
            with self.subTest(source=label):
                guid="indexer-"+label
                intake=receive(self.db,{"source":label,"source_guid":guid,
                    "release_name":RELEASE,"info_hash":("a" if label=="nyaa" else "b")*40})
                nid=intake["notification_id"]
                self.assertIsNotNone(self.db.execute(
                    "SELECT notification_id FROM anime_batch_pending WHERE notification_id=?",
                    (nid,)).fetchone())
                if label=="nyaa":
                    from anime_batch_verified_intake import authorize_verified_batch
                    import copy
                    report=copy.deepcopy(REPORT)
                    self.assertTrue(authorize_verified_batch(
                        self.db,nid,report,self.settings,XML))
                    self.assertEqual(report["batch_authorization"]["decision"],"ELIGIBLE")

    def test_replayed_original_webhook_restores_intake_without_auto_download(self):
        from anime_notification_management import recheck_unmatched_identity
        infohash="c"*40
        payload={"source":"nyaa","source_guid":"replay-existing-pack",
                 "release_name":RELEASE,"info_hash":infohash,
                 "magnet_uri":"magnet:?xt=urn:btih:"+infohash}
        first=receive(self.db,payload)
        nid=first["notification_id"]
        self.db.execute("DELETE FROM anime_batch_pending WHERE notification_id=?",(nid,))
        self.db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=?",(nid,))
        again=receive(self.db,payload)
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["notification_id"],nid)
        self.assertEqual(again["identity_status"],"NEEDS_REVIEW")
        self.assertIsNotNone(self.db.execute(
            "SELECT 1 FROM anime_batch_pending WHERE notification_id=?",(nid,)).fetchone())
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM anime_batch_authorizations WHERE notification_id=?",(nid,)).fetchone())
        self.assertEqual(recheck_unmatched_identity(self.db,nid)["status"],"IDENTIFYING")

    def test_legacy_indexer_pack_without_pending_has_actionable_blocker(self):
        from anime_batch_verified_intake import authorize_verified_batch
        import copy
        intake=receive(self.db,{"source":"nyaa","source_guid":"legacy-pack",
            "release_name":RELEASE,"info_hash":"c"*40})
        nid=intake["notification_id"]
        self.db.execute("DELETE FROM anime_batch_pending WHERE notification_id=?",(nid,))
        report=copy.deepcopy(REPORT)
        self.assertFalse(authorize_verified_batch(self.db,nid,report,self.settings,XML))
        self.assertEqual(report["issues"][0],"BATCH_PENDING_MAGNET_MISSING")
        self.assertEqual(report["batch_authorization"]["decision"],"BLOCKED")
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM anime_batch_authorizations WHERE notification_id=?",
            (nid,)).fetchone())

    def test_independently_verified_pack_gets_job_without_qb_submission(self):
        output=self.run_identity(REPORT.copy())
        self.assertEqual(output["processed"],1)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "APPROVED_BATCH")
        row=self.db.execute("""SELECT kind,state,subject_key FROM daemon_jobs
            WHERE kind='verified_batch_acquisition'""").fetchone()
        self.assertEqual(row,("verified_batch_acquisition","READY",str(self.nid)))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_batch_authorizations").fetchone()[0],1)

    def assert_blocked_reason(self, expected):
        from anime_dashboard_queries import all_jobs
        import json
        evidence=json.loads(self.db.execute(
            "SELECT evidence_json FROM unified_identity_checks WHERE notification_id=?",
            (self.nid,)).fetchone()[0])
        self.assertEqual(evidence["batch_authorization"]["reason"],expected)
        self.assertEqual(evidence["issues"][0],expected)
        self.assertIn("Batch authorization",
                      [s["step"] for s in evidence["workflow"]])
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "NEEDS_REVIEW")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone()[0],0)
        detail=all_jobs(self.db)["items"][0]["activity_detail"]
        self.assertIn(expected,detail)
        self.assertIn("Season-pack verification requires review",detail)
        self.assertNotIn("approve notification",detail)

    def test_real_cyberpunk_s02_batch_title_parses_unambiguously(self):
        from anime_batch_selection import release_scope_hint
        from anime_identification_probe import release_title
        from anime_identification_probe import norm
        release=("[Trix] Cyberpunk Edgerunners S02 1080p NF WEB-DL "
                 "Opus2.0 AV1 (Dual-Audio, Multi-Subs) (Season S2) (Batch)")
        hint=release_scope_hint(release)
        self.assertEqual(hint,{"kind":"season_pack","season_hint":2,
                                "episode_hint":None})
        names,episode=release_title(release)
        self.assertEqual(norm(names[0]),norm("Cyberpunk Edgerunners"))
        self.assertIsNone(episode)
        # The later PIN must separately agree with both this release's
        # season and an independently corroborated AniDB/TVDB provider pair.

    def test_cyberpunk_title_and_anime_lists_season2_anidb_are_selected_without_pin(self):
        from anime_batch_verified_intake import authorize_verified_batch
        from anime_trial_policy import window_for
        import json
        release=("[Trix] Cyberpunk Edgerunners S02 1080p NF WEB-DL "
                 "Opus2.0 AV1 (Dual-Audio, Multi-Subs) (Season S2) (Batch)")
        xml=(b'<anime-list>'
             b'<anime anidbid="15610" tvdbid="384541" defaulttvdbseason="1">'
             b'<name>Cyberpunk: Edgerunners</name></anime>'
             b'<anime anidbid="19445" tvdbid="384541" defaulttvdbseason="2">'
             b'<name>Cyberpunk: Edgerunners II</name></anime>'
             b'</anime-list>')
        report={"decision":"NEEDS_REVIEW",
            "matching_pairs":[{"tvdb_id":"384541","anidb_id":"15610"}],
            "issues":["BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
                      "EXACT_IDENTITY_NOT_VERIFIED"],
            "crossref_diagnostics":[{"tvdb_id":"384541","media_type":"ANIMATION",
                                     "matching_anidb_ids":["15610"]}]}
        incoming=receive(self.db,{"source":"autobrr",
            "source_guid":"cyberpunk-s02",
            "release_name":release,"info_hash":"c"*40})
        self.assertTrue(authorize_verified_batch(
            self.db,incoming["notification_id"],report,
            {"identity":{"series_map":{}}},xml))
        self.assertEqual(self.db.execute(
            "SELECT tvdb_id,anidb_id,season FROM anime_batch_authorizations "
            "WHERE notification_id=?",(incoming["notification_id"],)).fetchone(),
            ("384541","19445",2))
        window=window_for(self.db,tvdb_id=384541,anidb_id=19445,season=2)
        self.assertEqual((window["start"],window["end"]),(1,6))
        self.assertEqual(report["batch_season_mapping"]["initial_anidb_id"],"15610")
        self.assertEqual(report["batch_authorization"]["decision"],"ELIGIBLE")

    def test_cyberpunk_season2_mapping_missing_fails_closed(self):
        from anime_batch_verified_intake import authorize_verified_batch
        xml=(b'<anime-list><anime anidbid="15610" tvdbid="384541" '
             b'defaulttvdbseason="1"/></anime-list>')
        report={"decision":"NEEDS_REVIEW",
                "matching_pairs":[{"tvdb_id":"384541","anidb_id":"15610"}],
                "issues":["BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
                          "EXACT_IDENTITY_NOT_VERIFIED"],
                "crossref_diagnostics":[{"tvdb_id":"384541","media_type":"ANIMATION",
                                         "matching_anidb_ids":["15610"]}]}
        incoming=receive(self.db,{"source":"autobrr",
            "source_guid":"cyberpunk-s02-absent",
            "release_name":"Cyberpunk Edgerunners S02 (Batch)","info_hash":"d"*40})
        self.assertFalse(authorize_verified_batch(
            self.db,incoming["notification_id"],report,{"identity":{"series_map":{}}},xml))
        self.assertEqual(report["issues"][0],"BATCH_SEASON_MAPPING_UNAVAILABLE")

    def test_missing_explicit_season_is_actionable_not_generic_episode_error(self):
        # A release such as "Cyberpunk Edgerunners (Batch)" proves packaging,
        # not the TVDB season. Do not default an unlabeled pack to S01.
        self.db.execute("UPDATE notifications SET release_name=? WHERE id=?",
                        ("Example Show (Batch)",self.nid))
        self.run_identity(REPORT.copy())
        self.assert_blocked_reason("BATCH_SEASON_HINT_REQUIRED")

    def test_no_recognized_names_still_automatically_authorizes_batch(self):
        self.settings["identity"]={"series_map":{}}
        self.run_identity(REPORT.copy())
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "APPROVED_BATCH")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone()[0],1)

    def test_pin_for_another_season_does_not_block_independent_proof(self):
        self.settings["identity"]={"series_map":{"Example Show":{
            "tvdb_id":123,"anidb_id":456,"season":1}}}
        self.run_identity(REPORT.copy())
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "APPROVED_BATCH")

    def test_series_pair_really_verified_but_pinned_ids_conflict(self):
        self.settings["identity"]={"series_map":{"Example Show":{
            "tvdb_id":999,"anidb_id":456,"season":2}}}
        self.run_identity(REPORT.copy())
        self.assert_blocked_reason("BATCH_PINNED_PROVIDER_PAIR_MISMATCH")

    def test_recheck_terminal_pack_after_correcting_pinned_alias(self):
        from anime_dashboard_queries import all_jobs
        from anime_notification_management import recheck_unmatched_identity
        self.settings["identity"]={"series_map":{"Example Show":{
            "tvdb_id":999,"anidb_id":456,"season":2}}}
        self.run_identity(REPORT.copy())
        self.assert_blocked_reason("BATCH_PINNED_PROVIDER_PAIR_MISMATCH")
        self.assertTrue(all_jobs(self.db)["items"][0]["can_recheck"])
        result=recheck_unmatched_identity(self.db,self.nid)
        self.assertEqual(result["status"],"IDENTIFYING")
        self.assertFalse(result["queued"])
        self.assertIsNone(self.db.execute(
            "SELECT 1 FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone())
        self.settings["identity"]={"series_map":{}}
        self.run_identity(REPORT.copy())
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "APPROVED_BATCH")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone()[0],1)
        with self.assertRaises(ValueError):
            recheck_unmatched_identity(self.db,self.nid)

    def test_provider_pair_conflict_creates_review_not_batch_job(self):
        report={**REPORT,"matching_pairs":[{"tvdb_id":"999","anidb_id":"456"}]}
        self.run_identity(report)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "NEEDS_REVIEW")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone()[0],0)

    def test_provider_proved_part_two_has_distinct_13_to_18_window(self):
        from anime_batch_verified_intake import authorize_verified_batch
        from anime_trial_policy import window_for,record_verified_window
        xml=(b'<anime-list><anime anidbid="456" tvdbid="123" '
             b'defaulttvdbseason="1" episodeoffset="12" /></anime-list>')
        settings={"identity":{"series_map":{"Example Show":{
            "tvdb_id":123,"anidb_id":456,"season":1}}}}
        with tempfile.TemporaryDirectory() as tmp:
            db_path=Path(tmp)/"unit.sqlite"
            initialize(db_path)
            with sqlite3.connect(db_path,isolation_level=None) as db:
                got=receive(db,{"source":"autobrr","source_guid":"part-two",
                    "release_name":"Example Show S01 Part 2 (Batch)",
                    "info_hash":"b"*40})
                self.assertTrue(authorize_verified_batch(db,got["notification_id"],
                    REPORT.copy(),settings,xml))
                window=window_for(db,tvdb_id=123,anidb_id=456,
                                  season=1,unit_key="part:2")
                self.assertEqual((window["start"],window["end"]),(13,18))
                record_verified_window(db,tvdb_id=123,anidb_id=456,season=1,
                     unit_key="season",mode="SEASON",start_episode=1,
                     evidence_ref="tvdb:123:first:cour")
                with self.assertRaisesRegex(ValueError,"Ambiguous"):
                    window_for(db,tvdb_id=123,anidb_id=456,season=1)
                self.assertEqual(window_for(db,tvdb_id=123,anidb_id=456,
                    season=1,unit_key="part:2")["start"],13)

    def test_missing_episode_mapping_without_provider_crossref_is_not_promoted(self):
        report={**REPORT,"matching_pairs":[]}
        self.run_identity(report)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)).fetchone()[0],
            "NEEDS_REVIEW")


if __name__=="__main__":
    unittest.main()
