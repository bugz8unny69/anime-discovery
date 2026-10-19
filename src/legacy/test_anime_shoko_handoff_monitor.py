"""Regression: post-Keep monitor only handles verified Anime Discovery imports."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_shoko_handoff_monitor import check_once

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"db.sqlite")
        with sqlite3.connect(self.path) as db:
            db.executescript("""
              CREATE TABLE series (id INTEGER PRIMARY KEY,status TEXT);
              CREATE TABLE sonarr_keep (series_id INTEGER,sonarr_id INTEGER);
              CREATE TABLE sonarr_import_manifest (series_id INTEGER,manifest_json TEXT);
              CREATE TABLE torrent_recovery_records (notification_id INTEGER,sha256 TEXT);
            """)
            db.execute("INSERT INTO series VALUES (3,'KEPT')")
            db.execute("INSERT INTO sonarr_keep VALUES (3,124)")
            db.execute("INSERT INTO sonarr_import_manifest VALUES (3,?)",
                (json.dumps([{"notification_id":9,"season":1,"episode":1,
                    "path":"/trial/ep.mkv"}]),))
            db.execute("INSERT INTO torrent_recovery_records VALUES (9,?)",("a"*64,))
        self.settings={"sonarr":{"enabled":True,"root_folder":"/mnt/media/Anime"},
            "shoko":{"enabled":True,"base_url":"https://shoko"},
            "daemon":{"database_path":self.path}}
        self.secrets={"shoko_api_key":"key"}
    def test_backfill_and_retry_does_not_write(self):
        counts={"verified":0,"inspected":0}
        def verifier(*args,**kwargs):
            counts["verified"]+=1
            return ["/mnt/media/Anime/ep.mkv"]
        def inspect(*args,**kwargs):
            counts["inspected"]+=1
            self.assertFalse(kwargs["verified_episode_identity"])
            return {"status":"NEEDS_EPISODE_IDENTITY","writes_enabled":False}
        for _ in range(2):
            result=check_once(self.settings,self.secrets,inspector=inspect,
                copy_verifier=verifier)
            self.assertEqual(result,{"processed":1,"errors":0})
        self.assertEqual(counts,{"verified":2,"inspected":2})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shoko_handoff").fetchone()[0],1)
    def test_digest_missing_fails_before_enqueue(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE torrent_recovery_records SET sha256='bad'")
        result=check_once(self.settings,self.secrets,
            copy_verifier=lambda *a,**kw: self.fail("Should not verify"))
        self.assertEqual(result["errors"],1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM shoko_handoff").fetchone()[0],0)
    def test_disabled(self):
        self.settings["shoko"]["enabled"]=False
        self.assertEqual(check_once(self.settings,self.secrets),{"processed":0,"disabled":True})

if __name__=="__main__":unittest.main()
