import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_daemon_entrypoint import configured_daemon

class DaemonEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        (self.path/"settings.json").write_text(json.dumps({"daemon":{"concurrency":2}}))
        (self.path/"secrets.json").write_text("{}")
        os.chmod(self.path/"secrets.json",0o600)
        self.db=self.path/"unified.db"
        sqlite3.connect(self.db).close()

    def test_no_handlers_fails_closed(self):
        with self.assertRaises(RuntimeError):
            configured_daemon(self.path,self.db,{})

    def test_reads_concurrency_without_running(self):
        async def handler(job):
            return "DONE"
        coroutine=configured_daemon(self.path,self.db,{"test":handler})
        self.assertEqual(coroutine.cr_frame.f_locals["concurrency"],2)
        coroutine.close()

    def test_does_not_create_missing_db(self):
        async def handler(job):
            return "DONE"
        with self.assertRaises(FileNotFoundError):
            configured_daemon(self.path,self.path/"missing.db",{"test":handler})

if __name__=="__main__":
    unittest.main()
