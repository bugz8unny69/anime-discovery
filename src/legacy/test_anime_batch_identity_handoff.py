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
