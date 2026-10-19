"""Offline live-path integration: webhook -> daemon -> stage -> qB source cleanup."""
import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_fresh_database import initialize
from anime_webhook_processing import receive
from anime_async_daemon import claim, finish
from anime_acquisition_handler import make_acquisition_handler
from test_anime_acquisition_end_to_end import FakeQB

HASH="a"*40


class RemovableQB(FakeQB):
    def __init__(self, source):
        super().__init__()
        self.source=source
        self.removals=[]
        self.fail_removal=False

    def remove_torrent(self,infohash,*,delete_files=False):
        if self.fail_removal:
            raise OSError("Simulated removal outage")
        self.removals.append((infohash,delete_files))
        self.present=False
        if delete_files:
            self.source.unlink(missing_ok=True)


class LiveAcquisitionIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.download=root/"downloads"
        self.trial=root/"trial"
        self.download.mkdir()
        self.trial.mkdir()
        self.source=self.download/"episode.mkv"
        self.source.write_bytes(b"offline media"*5000)
        self.dbpath=root/"anime.db"
        initialize(self.dbpath)
        self.db=sqlite3.connect(self.dbpath,isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.qb=RemovableQB(self.source)
        data={"release_name":"Example S01E02","source_guid":"s01e02",
              "info_hash":HASH,"tvdb_id":123,"anidb_id":456,
              "season":1,"episode":2}
        self.notification=receive(self.db,data)["notification_id"]
        self.handler=make_acquisition_handler(self.dbpath,lambda:self.qb,
             download_root=self.download,trial_root=self.trial,cleanup_source=True)

    def run_handler(self,job):
        with (patch("anime_media_flow.confirmed_jp_en",return_value=True),
              patch("anime_source_retention.confirmed_jp_en",return_value=True)):
            return asyncio.run(self.handler(job))

    def test_staging_finishes_before_torrent_and_source_removal(self):
        job=claim(self.db,allowed_kinds=["claimed_acquisition"])
        outcome=self.run_handler(job)
        finish(self.db,job["id"],job["lease_token"],outcome)
        self.assertEqual(outcome,"DONE")
        self.assertEqual(self.qb.removals,[(HASH,True)])
        self.assertFalse(self.source.exists())
        staged=Path(self.db.execute("SELECT staged_path FROM torrent_recovery_records").fetchone()[0])
        self.assertTrue(staged.is_file())
        self.assertEqual(self.db.execute("SELECT state FROM daemon_jobs").fetchone()[0],"DONE")
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"DONE")

    def test_cleanup_outage_retries_without_copying_media_twice(self):
        job=claim(self.db,allowed_kinds=["claimed_acquisition"])
        self.qb.fail_removal=True
        with self.assertRaisesRegex(OSError,"removal"):
            self.run_handler(job)
        self.assertEqual(self.db.execute("SELECT state FROM episode_dispatch").fetchone()[0],"DONE")
        staged=Path(self.db.execute("SELECT staged_path FROM torrent_recovery_records").fetchone()[0])
        self.assertTrue(staged.is_file())
        self.assertTrue(self.source.exists())
        self.qb.fail_removal=False
        job=claim(self.db,now=time.time()+301,allowed_kinds=["claimed_acquisition"])
        self.assertIsNotNone(job)
        outcome=self.run_handler(job)
        finish(self.db,job["id"],job["lease_token"],outcome)
        self.assertEqual(outcome,"DONE")
        self.assertEqual(self.qb.adds,1)
        self.assertEqual(self.qb.removals,[(HASH,True)])
        self.assertFalse(self.source.exists())
        self.assertTrue(staged.is_file())


if __name__=="__main__":
    unittest.main()
