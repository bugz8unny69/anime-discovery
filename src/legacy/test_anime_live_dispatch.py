import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_async_daemon import enqueue,run_workers
from anime_config_reload import ConfigManager

class LiveDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"jobs.db"
        with sqlite3.connect(self.db,isolation_level=None) as db:
            enqueue(db,"test","one","{}")
        (self.root/"settings.json").write_text('{"daemon":{"concurrency":1}}')
        (self.root/"secrets.json").write_text("{}")
        os.chmod(self.root/"secrets.json",0o600)

    async def test_handler_receives_versioned_snapshot(self):
        stop=asyncio.Event()
        versions=[]
        async def handler(job):
            versions.append(job["config_snapshot"].settings["daemon"]["concurrency"])
            stop.set()
            return "DONE"
        await asyncio.wait_for(run_workers(self.db,{"test":handler},concurrency=1,
                         stop=stop,config_manager=ConfigManager(self.root)),timeout=3)
        self.assertEqual(versions,[1])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT state FROM daemon_jobs").fetchone()[0],"DONE")

if __name__=="__main__":
    unittest.main()
