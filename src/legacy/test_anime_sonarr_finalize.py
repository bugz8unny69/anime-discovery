"""Offline coverage: Sonarr import succeeds before trial/torrent cleanup."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_sonarr_finalize import finalize_import

HASH="a"*40
class Response:
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.payload).encode()
class FakeQB:
    def __init__(self,record=None):
        self.record=record
        self.deleted=[]
    def torrent_details(self,infohash):
        return self.record
    def remove_torrent(self,infohash,*,delete_files):
        self.deleted.append((infohash,delete_files))
        self.record=None

class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.trial=base/"trial"
        self.root=base/"permanent"
        self.download=base/"download"
        for p in (self.trial,self.root,self.download):p.mkdir()
        self.stage=self.trial/"ep01.mkv"
        self.stage.write_bytes(b"content-for-hashing")
        self.dest=self.root/"ep01.mkv"
        self.dest.write_bytes(self.stage.read_bytes())
        self.digest=hashlib.sha256(self.stage.read_bytes()).hexdigest()
        self.path=base/"db.sqlite"
        initialize(self.path)
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.sid=self.db.execute("INSERT INTO series(source,external_id,title,status) VALUES ('tvdb','123','Demo','SONARR_IMPORT_PENDING')").lastrowid
        self.nid=self.db.execute("INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES ('autobrr','Demo','guid',?,1)",(HASH,)).lastrowid
        self.db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'DONE')",(self.nid,self.sid))
        self.db.execute("INSERT INTO torrent_recovery_records(notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at) VALUES (?,?,?,?,?,1)",(self.nid,HASH,"magnet",str(self.stage),self.digest))
        self.db.execute("CREATE TABLE sonarr_keep(series_id INTEGER PRIMARY KEY,sonarr_id INTEGER,tvdb_id TEXT)")
        self.db.execute("INSERT INTO sonarr_keep VALUES (?,?,?)",(self.sid,33,"123"))
        self.db.execute("CREATE TABLE sonarr_import_manifest(series_id INTEGER PRIMARY KEY,manifest_json TEXT,submitted_command_id INTEGER)")
        self.db.execute("INSERT INTO sonarr_import_manifest VALUES (?,?,?)",(self.sid,json.dumps([{"notification_id":self.nid,"season":1,"episode":1,"path":str(self.stage)}]),88))
        self.settings={"sonarr":{"base_url":"https://sonarr.example","root_folder":str(self.root)},
                       "storage":{"trial_root":str(self.trial),"download_root":str(self.download)}}
        self.secrets={"sonarr_api_key":"test-key"}
    def opener(self,request,timeout):
        url=request.full_url
        if "/command/" in url:return Response({"id":88,"status":"completed"})
        if "/episodefile?" in url:return Response([{"id":22,"path":str(self.dest)}])
        if "/episode?" in url:return Response([{"id":11,"seasonNumber":1,"episodeNumber":1,"episodeFileId":22}])
        raise AssertionError(url)
    def test_confirmed_copy_allows_removal(self):
        qb=FakeQB()
        result=finalize_import(self.db,self.sid,self.settings,self.secrets,qb=qb,opener=self.opener)
        self.assertTrue(result["complete"])
        self.assertFalse(self.stage.exists())
        self.assertTrue(self.dest.exists())
        self.assertEqual(self.db.execute("SELECT status FROM series WHERE id=?",(self.sid,)).fetchone()[0],"KEPT")
    def test_corrupt_copy_never_deletes(self):
        self.dest.write_bytes(b"different")
        qb=FakeQB()
        with self.assertRaises(RuntimeError):
            finalize_import(self.db,self.sid,self.settings,self.secrets,qb=qb,opener=self.opener)
        self.assertEqual(qb.deleted,[])
        self.assertTrue(self.stage.exists())
    def test_wrong_qb_path_never_deletes(self):
        qb=FakeQB({"save_path":str(self.root)})
        with self.assertRaises(RuntimeError):
            finalize_import(self.db,self.sid,self.settings,self.secrets,qb=qb,opener=self.opener)
        self.assertEqual(qb.deleted,[])
        self.assertTrue(self.stage.exists())
    def test_torrent_removed_only_after_destination_verification(self):
        folder=self.download/"subfolder"
        folder.mkdir()
        qb=FakeQB({"save_path":str(folder)})
        result=finalize_import(self.db,self.sid,self.settings,self.secrets,qb=qb,opener=self.opener)
        self.assertTrue(result["complete"])
        self.assertEqual(qb.deleted,[(HASH,True)])

if __name__=="__main__":unittest.main()
