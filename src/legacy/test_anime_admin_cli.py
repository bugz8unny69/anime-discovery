import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("anime_admin_cli",Path(__file__).with_name("anime-discovery-admin.py"))
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

class AdminCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        (self.dir/"settings.json").write_text("{}")
        (self.dir/"secrets.json").write_text("{}")
        os.chmod(self.dir/"secrets.json",0o600)

    def test_new_database_is_explicit_and_non_destructive(self):
        path=self.dir/"unified.db"
        cli.new_database(path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT status FROM schema_bootstrap").fetchone()[0],"PENDING_MIGRATIONS")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        with self.assertRaises(FileExistsError):
            cli.new_database(path)

    def test_settings_cli(self):
        cli.main(["--config-dir",str(self.dir),"settings","set","daemon.concurrency","6"])
        self.assertEqual(json.loads((self.dir/"settings.json").read_text())["daemon"]["concurrency"],6)

if __name__=="__main__":
    unittest.main()
