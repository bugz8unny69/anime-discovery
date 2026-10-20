"""Offline end-to-end verified pack -> qB E01 -> ffprobe -> six stage trial."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_webhook_processing import receive
from anime_batch_verified_intake import authorize_verified_batch
from anime_batch_worker import step, _episode_mapping
from anime_async_daemon import claim, finish
from anime_trial_size_policy import MB
from test_anime_qb_e01_probe import AbsoluteQB, HASH, MAGNET


XML=(b'<anime-list><anime anidbid="456" tvdbid="123" '
     b'defaulttvdbseason="2" episodeoffset="-12" /></anime-list>')
RELEASE="Example Show S02 (Season Pack)"
SETTINGS={"identity":{"series_map":{"Example Show":{"tvdb_id":123,"anidb_id":456,"season":2}}}}
REPORT={"decision":"NEEDS_REVIEW","matching_pairs":[{"tvdb_id":"123","anidb_id":"456"}],
        "issues":["BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
                  "EXACT_IDENTITY_NOT_VERIFIED"],
        "crossref_diagnostics":[{"tvdb_id":"123","media_type":"ANIMATION",
                                 "matching_anidb_ids":["456"]}]}


class SourceQB(AbsoluteQB):
    def __init__(self, source_root):
        super().__init__(ready_after=0)
        self.source_root=Path(source_root)
        self.done=set()
        self.sizes=[1000]*12

    def torrent_identity(self, infohash):
        raw=super().torrent_identity(infohash)
        return {**raw,"save_path":str(self.source_root)} if raw else None

    def torrent_files(self, infohash):
        files=super().torrent_files(infohash)
        for row in files:
            row["size"]=self.sizes[row["index"]]
            row["progress"]=1.0 if row["index"] in self.done else 0.0
        return files

    def stop_owned_torrent(self, infohash):
        self.stops+=1
        self.records[infohash]["state"]="pausedDL"
        return "pausedDL"

    def completed(self, *indices):
        folder=self.source_root/"Season 02"
        folder.mkdir(exist_ok=True)
        for i in indices:
            (folder/("Anime S02E%02d.mkv"%(i+13))).write_bytes(b"x"*self.sizes[i])
            self.done.add(i)


class VerifiedBatchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.download=self.root/"downloads"
        self.trial=self.root/"trials"
        self.download.mkdir()
        self.trial.mkdir()
        self.db_path=self.root/"db.sqlite"
        initialize(self.db_path)
        self.db=sqlite3.connect(self.db_path,isolation_level=None)
        self.addCleanup(self.db.close)
        (self.root/"anime-lists.xml").write_bytes(XML)
        result=receive(self.db,{"source":"autobrr","source_guid":"pack-1",
            "release_name":RELEASE,"info_hash":HASH,"magnet_uri":MAGNET})
        self.nid=result["notification_id"]
        self.qb=SourceQB(self.download)
        self.settings={"trial":{"max_episode_mb":600,"max_six_episode_mb":3000},
                       "daemon":{"database_path":str(self.db_path)}}

    def approve(self):
        self.assertTrue(authorize_verified_batch(
            self.db,self.nid,REPORT,SETTINGS,XML))
        self.db.execute("UPDATE notifications SET status='APPROVED_BATCH' WHERE id=?",
                        (self.nid,))
        self.job=claim(self.db,now=time.time(),allowed_kinds=["verified_batch_acquisition"])
        self.assertIsNotNone(self.job)

    def step(self):
        return step(self.db,self.job,self.qb,download_root=self.download,
                    trial_root=self.trial,settings=self.settings,runner=lambda _:True)

    def test_no_batch_submission_without_independent_provider_evidence(self):
        self.assertFalse(authorize_verified_batch(
            self.db,self.nid,{**REPORT,"matching_pairs":[{"tvdb_id":"999","anidb_id":"456"}]},
            SETTINGS,XML))
        self.assertEqual(self.qb.adds,0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs WHERE kind='verified_batch_acquisition'").fetchone()[0],0)

    def test_batch_700mb_first_file_is_eligible_when_six_total_under_budget(self):
        self.approve()
        self.qb.sizes=[700*MB]+[400*MB]*5+[900*MB]*6
        self.assertEqual(self.step(),"DEFERRED")
        self.assertEqual(self.qb.start_calls,1)
        self.assertEqual(self.qb.priorities[0],1)
        self.assertTrue(all(self.qb.priorities[i]==0 for i in range(1,12)))

    def test_complete_first_episode_unlock_and_independent_staging(self):
        self.approve()
        self.assertEqual(self.step(),"DEFERRED")
        # A retry after the manifest is committed must not add another magnet.
        self.assertEqual(self.step(),"DEFERRED")
        self.assertEqual(self.qb.adds,1)
        self.assertEqual(self.qb.start_calls,1)
        self.qb.completed(0)
        self.assertEqual(self.step(),"DEFERRED")
        self.assertEqual(self.qb.start_calls,2)
        self.assertEqual([self.qb.priorities[x] for x in range(12)],[1]*6+[0]*6)
        first=self.trial/"Example Show"/"Season 02"/"S02E01.mkv"
        self.assertTrue(first.is_file())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM anime_batch_audio_proofs").fetchone()[0],1)
        self.qb.completed(1,2,3,4,5)
        self.assertEqual(self.step(),"DONE")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM anime_batch_staged").fetchone()[0],6)
        self.assertEqual(self.db.execute("SELECT state FROM anime_batch_executions").fetchone()[0],"DONE")
        self.assertEqual(self.qb.adds,1)
        self.assertEqual(self.qb.start_calls,2)
        self.assertTrue((self.trial/"Example Show"/"Season 02"/"S02E06.mkv").is_file())
        self.assertEqual(self.step(),"DONE")
        self.assertEqual(self.qb.start_calls,2)

    def test_outside_download_root_is_safe_review_not_identity_failure(self):
        from anime_dashboard_queries import all_jobs
        self.approve()
        self.assertEqual(self.step(),"DEFERRED")
        self.qb.completed(0)
        self.qb.source_root=self.root/"external-download"
        with self.assertRaisesRegex(ValueError,"qBittorrent save path outside download root"):
            self.step()
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anime_batch_staged").fetchone()[0],0)
        self.db.execute("""UPDATE daemon_jobs SET state='NEEDS_REVIEW',
            last_error='QBITTORRENT_SAVE_PATH_OUTSIDE_DOWNLOAD_ROOT'
            WHERE id=?""",(self.job["id"],))
        row=next(x for x in all_jobs(self.db)["items"] if x["id"]==self.nid)
        self.assertIn("save_path",row["activity_detail"])
        self.assertIn("storage.download_root",row["activity_detail"])
        self.assertNotIn("BATCH_FILE_MANIFEST_REQUIRED",row["activity_detail"])
        self.assertNotIn("EXACT_IDENTITY_NOT_VERIFIED",row["activity_detail"])

    def test_bad_audio_blocks_unlock(self):
        self.approve()
        self.assertEqual(self.step(),"DEFERRED")
        self.qb.completed(0)
        with self.assertRaisesRegex(ValueError,"JAPANESE_ENGLISH_REQUIRED"):
            step(self.db,self.job,self.qb,download_root=self.download,
                 trial_root=self.trial,settings=self.settings,runner=lambda _:False)
        self.assertEqual(self.qb.start_calls,1)
        self.assertEqual(self.qb.priorities[1],0)

    def test_verified_part_two_supports_reset_and_absolute_numbering(self):
        from anime_trial_policy import window_for
        xml=(b'<anime-list><anime anidbid="456" tvdbid="123" '
             b'defaulttvdbseason="1" episodeoffset="12" /></anime-list>')
        reset=[{"index":i,"name":"Season 01/Example Show S01 Part 2 - %02d.mkv"%(i+1)}
               for i in range(12)]
        absolute=[{"index":i,"name":"Season 01/Example Show S01 Part 2 - %02d.mkv"%(i+13)}
                  for i in range(12)]
        self.assertEqual(_episode_mapping(reset,season=1,tvdb_id=123,
            anidb_id=456,xml_bytes=xml,start_episode=13,mode="PART"),
            {i:i+12 for i in range(1,13)})
        self.assertEqual(_episode_mapping(absolute,season=1,tvdb_id=123,
            anidb_id=456,xml_bytes=xml,start_episode=13,mode="PART"),
            {i:i for i in range(13,25)})

    def test_relative_labels_and_absolute_provider_numbers_both_work(self):
        import copy
        files=[{"index":i,"name":"Season 02/Show S02E%02d.mkv"%(i+1)}
               for i in range(12)]
        # In the provider's AniDB feed episode 13 becomes canonical S02E01,
        # but these files already carry explicit *season-relative* names.
        self.assertEqual(_episode_mapping(files,season=2,tvdb_id=123,
                            anidb_id=456,xml_bytes=XML),{i:i for i in range(1,13)})
        absfiles=[{"index":i,"name":"Season 02/Show S02E%02d.mkv"%(i+13)}
                  for i in range(12)]
        self.assertEqual(_episode_mapping(absfiles,season=2,tvdb_id=123,
                            anidb_id=456,xml_bytes=XML),{i:i-12 for i in range(13,25)})


if __name__=="__main__":
    unittest.main()
