"""Shoko best-effort handoff monitor full-flow integration with mocked APIs."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_shoko_handoff_monitor import check_once

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path=str(Path(self.temp.name)/"db.sqlite")
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
            CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,status TEXT);
            CREATE TABLE sonarr_keep(series_id INTEGER,sonarr_id INTEGER);
            CREATE TABLE sonarr_import_manifest(series_id INTEGER,manifest_json TEXT);
            CREATE TABLE torrent_recovery_records(notification_id INTEGER,sha256 TEXT);
            CREATE TABLE verified_series_identity(notification_id INTEGER,anidb_id TEXT,tvdb_id TEXT);
            """)
            db.execute("INSERT INTO series VALUES (3,'tvdb','50','KEPT')")
            db.execute("INSERT INTO sonarr_keep VALUES (3,124)")
            db.execute("INSERT INTO sonarr_import_manifest VALUES (3,?)",
                (json.dumps([{"notification_id":9,"season":1,"episode":1,
                    "path":"/trial/ep.mkv"}]),))
            db.execute("INSERT INTO torrent_recovery_records VALUES (9,?)",("a"*64,))
            db.execute("INSERT INTO verified_series_identity VALUES (9,'123','50')")
        self.cfg={"sonarr":{"enabled":True,"root_folder":"/mnt/media/Anime"},
                  "shoko":{"enabled":True,"base_url":"https://shoko",
                           "auto_link_verified":True,"import_folder_id":1},
                  "ntfy":{"enabled":False},"identity":{"episode_map":{
                    "50:1:1":{"anidb_episode_id":555,"verified":True}}},
                  "daemon":{"database_path":self.db_path}}
        self.sec={"shoko_api_key":"key"}
    def verifier(self,*args,**kwargs):
        self.assertEqual(kwargs["expected_digests"],{9:"a"*64})
        return ["/mnt/media/Anime/ep.mkv"]
    def test_complete_safe_link_and_idempotency(self):
        calls=[]
        def inspector(*args,**kwargs):
            self.assertTrue(kwargs["verified_episode_identity"])
            self.assertEqual(kwargs["anidb_episode_id"],555)
            return {"status":"LINK_PLAN_READY","file_id":62,
                    "shoko_episode_id":876,"anidb_episode_id":555,
                    "writes_enabled":False}
        def linker(*args,**kwargs):
            calls.append(kwargs)
            self.assertTrue(kwargs["allow_writes"])
            self.assertEqual(kwargs["file_id"],62)
            return "SHOKO_LINK_VERIFIED"
        with patch("anime_shoko_handoff_monitor.link_verified",side_effect=linker):
            for _ in range(2):
                result=check_once(self.cfg,self.sec,inspector=inspector,
                    copy_verifier=self.verifier)
                self.assertEqual(result["errors"],0)
        self.assertEqual(len(calls),1)
        with sqlite3.connect(self.db_path) as db:
            row=db.execute("""SELECT anidb_episode_id,identity_verified,status
                FROM shoko_handoff WHERE series_id=3 AND notification_id=9""").fetchone()
            self.assertEqual(row,(555,1,"SHOKO_LINK_VERIFIED"))
    def test_scan_runs_only_once_when_missing(self):
        self.cfg["identity"]["episode_map"]={}
        self.cfg["shoko"]["auto_link_verified"]=False
        scans=[]
        def inspector(*args,**kwargs):
            return {"status":"AWAITING_SHOKO_SCAN","writes_enabled":False}
        def scan(*args,**kwargs):
            scans.append((args,kwargs))
            return True
        with patch("anime_shoko_handoff_monitor.request_scan",side_effect=scan):
            for _ in range(2):
                result=check_once(self.cfg,self.sec,inspector=inspector,
                    copy_verifier=self.verifier)
                self.assertEqual(result["errors"],0)
        self.assertEqual(len(scans),1)
        self.assertEqual(scans[0][1]["expected_root"],"/mnt/media/Anime")
        self.assertEqual(scans[0][0][2],1)

if __name__=="__main__":unittest.main()
