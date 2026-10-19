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
        self.nid=self.db.execute("INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES ('autobrr','Example E01','demo','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0)").lastrowid
        self.db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'DONE')",(self.nid,self.sid))
        stage=Path(self.tmp.name)/"episode.mkv"
        stage.write_bytes(b"fixture")
        self.db.execute("INSERT INTO torrent_recovery_records(notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at) VALUES (?,'hash','magnet',?,'hash',0)",(self.nid,str(stage)))
        self.settings={"storage":{"trial_root":self.tmp.name},"sonarr":{"enabled":True,"base_url":"https://sonarr.example","root_folder":"/mnt/media/Anime","quality_profile_id":4}}
        self.secrets={"sonarr_api_key":"not-a-live-key"}
    def test_keep_persists_only_after_confirmation(self):
        result=keep(self.db,self.sid,self.settings,self.secrets,sonarr_client=lambda *a,**k:{"sonarr_id":22})
        self.assertEqual(result["sonarr_id"],22)
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"SONARR_IMPORT_PENDING")
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
            if request.full_url.endswith("/qualityprofile"):
                return Response([{"id":4,"name":"Anime"}])
            if request.full_url.endswith("/rootfolder"):
                return Response([{"path":"/mnt/media/Anime"}])
            return Response([{"tvdbId":123,"id":7}])
        result=ensure_series(self.settings,self.secrets,tvdb_id="123",title="Example",opener=fake)
        self.assertTrue(result["already_exists"])
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0][0],"GET")
        self.assertEqual(calls[0][2],"not-a-live-key")

if __name__=="__main__": unittest.main()
