"""Offline end-to-end acquisition test with real SQLite, staging and hashes.

Only identity approval and ffprobe are mocked; qBittorrent is an in-memory
transport and every file is created inside TemporaryDirectory.
"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from anime_async_daemon import ensure_schema, claim, finish
from anime_acquisition_handler import make_acquisition_handler
import asyncio

HASH="a"*40
MAGNET="magnet:?xt=urn:btih:"+HASH
APPROVAL={"notification_id":7,"series_id":4,"season":1,"episode":1}

class FakeQB:
    def __init__(self):
        self.adds=0
        self.present=False
        self.category=""
        self.tag=""
    def contains_hash(self, key):
        return self.present and key==HASH
    def torrent_identity(self,key):
        return ({"hash":HASH,"category":self.category,"tags":self.tag}
                if self.present and key==HASH else None)
    def add_magnet(self, magnet, *, category, tag):
        if magnet!=MAGNET:
            raise ValueError("Wrong magnet")
        self.adds+=1
        self.category=category
        self.tag=tag
        self.present=True
    def _request(self, endpoint):
        path,_,query=endpoint.partition("?")
        args=parse_qs(query)
        if path=="torrents/info":
            assert args["hashes"]==[HASH]
            return json.dumps([{"hash":HASH,"progress":1,"state":"uploading"}] if self.present else [])
        if path=="torrents/files":
            assert args["hash"]==[HASH]
            return json.dumps([{"name":"episode.mkv","progress":1}])
        raise AssertionError(endpoint)

class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.download=self.root/"downloads"
        self.trial=self.root/"trial"
        self.download.mkdir()
        self.trial.mkdir()
        self.source=self.download/"episode.mkv"
        self.source.write_bytes(b"offline test media bytes"*4096)
        self.dbpath=self.root/"state.sqlite"
        self.qb=FakeQB()
        with self.connect() as db:
            ensure_schema(db)
            db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT)")
            db.execute("INSERT INTO notifications VALUES(7,?)",(HASH,))
            db.execute("CREATE TABLE verified_series_identity(notification_id INTEGER,tvdb_id TEXT)")
            db.execute("INSERT INTO verified_series_identity VALUES(7,'123')")
            db.execute("CREATE TABLE episode_dispatch(notification_id INTEGER PRIMARY KEY,state TEXT,last_error TEXT,updated_at INTEGER)")
            db.execute("INSERT INTO episode_dispatch VALUES(7,'CLAIMED',NULL,0)")
            db.execute("INSERT INTO daemon_jobs(kind,subject_key,payload_json,state) VALUES(?,?,?,'READY')",
                ("claimed_acquisition","7",json.dumps({
                    "notification_id":7,"infohash":HASH,"magnet_uri":MAGNET,
                    "title":"Example","tvdb_id":123})))
    def connect(self):
        return sqlite3.connect(self.dbpath,isolation_level=None)
    def run_claim(self):
        with self.connect() as db:
            job=claim(db,allowed_kinds=["claimed_acquisition"])
        self.assertIsNotNone(job)
        handler=make_acquisition_handler(self.dbpath,lambda:self.qb,
            download_root=self.download,trial_root=self.trial)
        with (patch("anime_acquisition_handler.approved_dispatch",return_value=APPROVAL),
              patch("anime_claimed_pipeline.approved_dispatch",return_value=APPROVAL),
              patch("anime_acquisition_flow.approved_dispatch",return_value=APPROVAL),
              patch("anime_media_flow.approved_dispatch",return_value=APPROVAL),
              patch("anime_acquisition_finalize.approved_dispatch",return_value=APPROVAL),
              patch("anime_media_flow.confirmed_jp_en",return_value=True),
              patch("anime_source_retention.confirmed_jp_en",return_value=True)):
            outcome=asyncio.run(handler(job))
        with self.connect() as db:
            finish(db,job["id"],job["lease_token"],outcome)
        return outcome
    def test_complete_pipeline_and_sha256(self):
        self.assertEqual(self.run_claim(),"DONE")
        staged=self.trial/"TVDB-123-S4"/"Season 01"/"S01E01.mkv"
        self.assertTrue(staged.is_file())
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(),digest)
        self.assertEqual(self.qb.adds,1)
        self.assertTrue(self.source.is_file())
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"DONE")
            self.assertEqual(db.execute("SELECT sha256 FROM torrent_recovery_records").fetchone()[0],digest)
            self.assertEqual(db.execute("SELECT state FROM daemon_jobs").fetchone()[0],"DONE")
    def test_preexisting_staged_file_reconciles_after_restart(self):
        staged=self.trial/"TVDB-123-S4"/"Season 01"/"S01E01.mkv"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(self.source.read_bytes())
        self.assertEqual(self.run_claim(),"DONE")
        self.assertEqual(self.qb.adds,1)
        self.assertTrue(self.source.exists())
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM torrent_recovery_records").fetchone()[0],1)
    def test_corrupt_preexisting_stage_never_finalizes(self):
        staged=self.trial/"TVDB-123-S4"/"Season 01"/"S01E01.mkv"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError,"size"):
            self.run_claim()
        self.assertEqual(staged.read_bytes(),b"corrupt")
        self.assertTrue(self.source.exists())
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"CLAIMED")

    def test_interrupted_copy_preserves_source_and_cleans_temp(self):
        # Inject an I/O failure before the staged video is published.
        with patch("anime_trial_staging.os.link",side_effect=OSError("simulated crash")):
            with self.assertRaisesRegex(OSError,"simulated crash"):
                self.run_claim()
        self.assertTrue(self.source.exists())
        season=self.trial/"TVDB-123-S4"/"Season 01"
        self.assertFalse((season/"S01E01.mkv").exists())
        self.assertEqual(list(season.glob(".anime-stage-*")),[])
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"CLAIMED")
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='torrent_recovery_records'").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
