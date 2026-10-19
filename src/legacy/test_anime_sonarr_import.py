"""Offline Sonarr import preparation tests; no remote or destructive operations."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_sonarr_import import plan_staged_imports

class StagedPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"trial"
        self.root.mkdir()
        initialize(Path(self.tmp.name)/"db.sqlite")
        self.db=sqlite3.connect(Path(self.tmp.name)/"db.sqlite",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.sid=self.db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Example')").lastrowid
        nid=self.db.execute("INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES ('autobrr','Episode 1','guid','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',0)").lastrowid
        self.db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'DONE')",(nid,self.sid))
        self.path=self.root/"episode.mkv"
        self.path.write_bytes(b"test media")
        self.db.execute("INSERT INTO torrent_recovery_records(notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at) VALUES (?,'hash','magnet',?,'sha',0)",(nid,str(self.path)))
    def test_exact_path_is_planned(self):
        plan=plan_staged_imports(self.db,self.sid,trial_root=self.root)
        self.assertEqual(plan[0]["path"],str(self.path))
        self.assertEqual(plan[0]["episode"],1)
    def test_missing_media_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            plan_staged_imports(self.db,self.sid,trial_root=self.root)
    def test_outside_trial_root_is_rejected(self):
        outside=Path(self.tmp.name)/"other.mkv"
        outside.write_bytes(b"test")
        self.db.execute("UPDATE torrent_recovery_records SET staged_path=?",(str(outside),))
        with self.assertRaises(ValueError):
            plan_staged_imports(self.db,self.sid,trial_root=self.root)

if __name__=="__main__":unittest.main()
