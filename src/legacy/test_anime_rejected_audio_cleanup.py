"""Offline rejected-audio cleanup orchestration; never contacts real qBittorrent."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_cancel_cleanup import cleanup_rejected_dual_audio
from anime_episode_acquisition_guard import reserve

HASH="a"*40
class FakeQB:
    def __init__(self,path,*,fails=False):
        self.path=path
        self.fails=fails
        self.removed=False
        self.stopped=False
    def torrent_identity(self,infohash):
        if self.removed:
            return None
        return {"hash":HASH,"category":"anime-discovery","tags":"ad-"+"f"*32}
    def stop_owned_torrent(self,infohash):
        self.stopped=True
    def remove_torrent(self,infohash,*,delete_files=False):
        if self.fails:
            raise RuntimeError("simulated ambiguous removal")
        assert delete_files and self.stopped
        self.path.unlink()
        self.removed=True

class AudioCleanupTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.download=root/"download"
        self.trial=root/"trial"
        self.download.mkdir()
        self.trial.mkdir()
        self.video=self.download/"sample.mkv"
        self.video.write_bytes(b"fake video")
        self.db=sqlite3.connect(root/"queue.db",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT);
          CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT);
          CREATE TABLE episode_dispatch(notification_id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,state TEXT);
          CREATE TABLE torrent_recovery_records(notification_id INTEGER,infohash TEXT);
          CREATE TABLE anime_batch_authorizations(notification_id INTEGER,infohash TEXT);
          CREATE TABLE qb_torrent_ownership(infohash TEXT,status TEXT,marker TEXT,category TEXT);
          CREATE TABLE daemon_jobs(id INTEGER PRIMARY KEY,kind TEXT,state TEXT,lease_token TEXT,lease_until REAL,subject_key TEXT,available_at REAL,last_error TEXT);
        """)
        self.db.execute("INSERT INTO notifications VALUES (1,?)",(HASH,))
        self.db.execute("INSERT INTO notifications VALUES (2,?)",("b"*40,))
        self.db.execute("INSERT INTO series VALUES (1,'tvdb','123')")
        self.db.execute("INSERT INTO episode_dispatch VALUES(1,1,1,1,'CLAIMED')")
        self.db.execute("INSERT INTO episode_dispatch VALUES(2,1,1,1,'CLAIMED')")
        self.db.execute("INSERT INTO qb_torrent_ownership VALUES(?,'OWNED',?,'anime-discovery')",
                        (HASH,"ad-"+"f"*32))
        self.db.execute("""INSERT INTO daemon_jobs VALUES(8,'claimed_acquisition','LEASED',
            'lease123',9999999999,'1',0,NULL)""")
        self.assertEqual(reserve(self.db,1),"OWNER")
        self.job={"id":8,"lease_token":"lease123","notification_id":1}
        self.qb=FakeQB(self.video)
        self.plan={"files":[str(self.video)],"bytes":len(b"fake video"),"fingerprints":{}}
    def run_cleanup(self):
        with patch("anime_cleanup_file_safety.preflight",return_value=self.plan):
            return cleanup_rejected_dual_audio(self.db,self.job,HASH,self.qb,
                download_root=self.download,trial_root=self.trial)
    def test_confirmed_cleanup_releases_next_group(self):
        self.assertTrue(self.run_cleanup())
        self.assertFalse(self.video.exists())
        self.assertEqual(reserve(self.db,2),"OWNER")
        row=self.db.execute("SELECT state FROM anime_rejected_audio_cleanup WHERE job_id=8").fetchone()
        self.assertEqual(row[0],"REMOVED")
    def test_uncertain_cleanup_never_releases_owner(self):
        self.qb.fails=True
        with self.assertRaises(RuntimeError):
            self.run_cleanup()
        self.assertTrue(self.video.exists())
        self.assertEqual(reserve(self.db,2),"ON_HOLD")
        self.assertEqual(self.db.execute("SELECT state FROM anime_rejected_audio_cleanup WHERE job_id=8").fetchone()[0],
                         "UNCERTAIN")
    def test_unowned_torrent_is_not_deleted(self):
        self.db.execute("UPDATE qb_torrent_ownership SET status='EXTERNAL'")
        with self.assertRaises(ValueError):
            self.run_cleanup()
        self.assertTrue(self.video.exists())
        self.assertFalse(self.qb.stopped)
        self.assertEqual(reserve(self.db,2),"ON_HOLD")
    def test_shared_torrent_is_not_deleted(self):
        self.db.execute("UPDATE notifications SET info_hash=? WHERE id=2",(HASH,))
        with self.assertRaises(ValueError):
            self.run_cleanup()
        self.assertFalse(self.qb.stopped)
        self.assertTrue(self.video.exists())

if __name__=="__main__":
    unittest.main()
