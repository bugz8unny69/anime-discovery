"""No live Sonarr/qB operations: explicit duplicate cleanup regression coverage."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize
from anime_sonarr_duplicate_cleanup import review,confirm

class Reply:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return json.dumps(self.data).encode()

class FakeQB:
    def __init__(self):
        self.removed=[]
    def remove_torrent(self,h,delete_files=False):
        self.removed.append((h,delete_files))

class DuplicateCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.trial=self.base/"trial"
        self.dest=self.base/"sonarr"
        self.down=self.base/"downloads"
        for d in (self.trial,self.dest,self.down):d.mkdir()
        dbfile=self.base/"db.sqlite"
        initialize(dbfile)
        self.db=sqlite3.connect(dbfile,isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.sid=self.db.execute(
            "INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Solo Leveling')").lastrowid
        self.paths=[]
        for episode in (1,2):
            nid=self.db.execute("""INSERT INTO notifications
                (source,release_name,source_guid,info_hash,received_at)
                VALUES ('autobrr',?,?,?,0)""",
                ("Solo E"+str(episode),"solo-"+str(episode),"a"*40)).lastrowid
            self.db.execute("""INSERT INTO episode_dispatch
                (notification_id,series_id,season,episode,state)
                VALUES (?,?,1,?,'DONE')""",(nid,self.sid,episode))
            source=self.trial/("E%02d.mkv"%episode)
            source.write_bytes(("distinct trial episode "+str(episode)).encode())
            self.paths.append((nid,source))
            self.db.execute("""INSERT INTO torrent_recovery_records
                (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
                VALUES (?,?,?,?,?,0)""",
                (nid,("a" if episode==1 else "b")*40,"magnet",
                 str(source),hashlib.sha256(source.read_bytes()).hexdigest()))
            (self.dest/("E%02d.mkv"%episode)).write_bytes(b"an existing Sonarr release")
        self.settings={"storage":{"trial_root":str(self.trial),
                "download_root":str(self.down)},
            "sonarr":{"base_url":"https://sonarr.example",
                "root_folder":str(self.dest)}}
        self.secrets={"sonarr_api_key":"dummy"}
        self.calls=[]

    def opener(self,req,timeout):
        self.calls.append((req.get_method(),req.full_url))
        if req.full_url.endswith("/series"):
            return Reply([{"id":124,"tvdbId":123,"monitored":True}])
        if "episode?seriesId=" in req.full_url:
            return Reply([{"id":700+i,"seasonNumber":1,"episodeNumber":i,
                           "hasFile":True,"episodeFileId":900+i} for i in (1,2)])
        if "episodefile?seriesId=" in req.full_url:
            return Reply([{"id":900+i,"seriesId":124,"size":100,
                           "path":str(self.dest/("E%02d.mkv"%i))}
                          for i in (1,2)])
        raise AssertionError("Unexpected Sonarr request "+req.full_url)

    def test_review_is_read_only_and_audio_required(self):
        result=review(self.db,self.sid,self.settings,self.secrets,
                      opener=self.opener,audio_probe=lambda p:True)
        self.assertEqual(result["eligible"],2)
        self.assertFalse(result["cleanup_authorized"])
        self.assertEqual(len(self.paths),2)
        self.assertTrue(all(path.is_file() for _,path in self.paths))
        self.assertTrue(all(method=="GET" for method,_ in self.calls))
        blocked=review(self.db,self.sid,self.settings,self.secrets,
                       opener=self.opener,audio_probe=lambda p:False)
        self.assertEqual(blocked["eligible"],0)

    def test_requires_explicit_confirmation(self):
        with self.assertRaises(PermissionError):
            confirm(self.db,self.sid,self.settings,self.secrets,qb=FakeQB(),
                    opener=self.opener,audio_probe=lambda p:True)
        self.assertTrue(all(path.is_file() for _,path in self.paths))

    def test_confirm_cleans_verified_trial_files_but_preserves_external_torrents(self):
        qb=FakeQB()
        result=confirm(self.db,self.sid,self.settings,self.secrets,
                       approved=True,qb=qb,opener=self.opener,audio_probe=lambda p:True)
        self.assertEqual(len(result["removed_notification_ids"]),2)
        self.assertEqual(qb.removed,[])
        self.assertEqual(len(result["preserved_torrents"]),2)
        self.assertTrue(all(not path.exists() for _,path in self.paths))
        self.assertTrue(all((self.dest/("E%02d.mkv"%i)).exists() for i in (1,2)))
        self.assertEqual(self.db.execute(
            "SELECT result FROM sonarr_duplicate_cleanup_audit").fetchone()[0],"COMPLETED")

    def test_symlink_staged_file_refused(self):
        outside=self.base/"outside.mkv"
        outside.write_bytes(b"do not delete")
        nid,path=self.paths[0]
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            review(self.db,self.sid,self.settings,self.secrets,
                   opener=self.opener,audio_probe=lambda p:True)
        self.assertTrue(outside.exists())

if __name__=="__main__":unittest.main()
