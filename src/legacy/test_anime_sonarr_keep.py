"""Offline regression tests for Sonarr KEEP and failures."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_series_lifecycle import keep
from anime_sonarr import ensure_series

class KeepTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbpath=Path(self.tmp.name)/"db.sqlite"
        initialize(self.dbpath)
        self.db=sqlite3.connect(self.dbpath,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.sid=self.db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Example')").lastrowid
        self.settings={"sonarr":{"enabled":True,"base_url":"https://sonarr.example","root_folder":"/mnt/media/Anime","quality_profile_id":4}}
        self.secrets={"sonarr_api_key":"not-a-live-key"}
    def test_keep_persists_only_after_confirmation(self):
        result=keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=lambda *a,**k:{"sonarr_id":22})
        self.assertEqual(result["sonarr_id"],22)
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"KEPT")
        self.assertEqual(self.db.execute("SELECT tvdb_id FROM sonarr_keep").fetchone()[0],"123")
    def test_failed_sonarr_does_not_keep(self):
        def unavailable(*a,**kw):
            raise RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=unavailable)
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"DISCOVERED")
    def test_rejected_never_calls_sonarr(self):
        self.db.execute("UPDATE series SET status='REJECTED' WHERE id=?",(self.sid,))
        with self.assertRaises(ValueError):
            keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=lambda *a,**k:self.fail("called"))
    def test_sonarr_existing_id_no_duplicate_post(self):
        class Response:
            def __init__(self,data): self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(self.data).encode()
        calls=[]
        def fake(request,timeout):
            calls.append((request.get_method(),request.full_url,request.get_header("X-api-key")))
            return Response([{"tvdbId":123,"id":7}])
        result=ensure_series(self.settings,self.secrets,tvdb_id="123",title="Example",opener=fake)
        self.assertTrue(result["already_exists"])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],"GET")
        self.assertEqual(calls[0][2],"not-a-live-key")

if __name__=="__main__": unittest.main()
