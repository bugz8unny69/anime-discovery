"""Offline tests for the built-in upgrade and grouped admin commands."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_admin_upgrade import upgrade
from anime_fresh_database import initialize

spec=importlib.util.spec_from_file_location("anime_admin_upgrade_cli",
    Path(__file__).with_name("anime-discovery-admin.py"))
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        (self.root/".git").mkdir()
        self.db=self.root/"data.db"
        initialize(self.db)
        self.calls=[]

    def runner(self,*args,cwd=None):
        self.calls.append(args)
        lookups={
            ("git","status","--porcelain"):"",
            ("git","branch","--show-current"):"develop",
            ("git","rev-parse","HEAD"):"old",
            ("git","rev-parse","FETCH_HEAD"):"new",
            ("git","merge-base","old","new"):"old"
        }
        return lookups.get(args,"")

    def test_fast_forward_stops_service_makes_backup_and_restarts(self):
        result=upgrade(self.root,db_path=self.db,runner=self.runner)
        self.assertTrue(result["updated"])
        self.assertTrue(Path(result["backup"]).is_file())
        with sqlite3.connect(result["backup"]) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        self.assertIn(("systemctl","stop","anime-discovery.service"),self.calls)
        self.assertIn(("git","merge","--ff-only","FETCH_HEAD"),self.calls)
        self.assertIn(("systemctl","start","anime-discovery.service"),self.calls)

    def test_dirty_worktree_never_stops_service(self):
        def runner(*args,cwd=None):
            return "modified" if args==("git","status","--porcelain") else self.runner(*args,cwd=cwd)
        with self.assertRaisesRegex(ValueError,"local changes"):
            upgrade(self.root,db_path=self.db,runner=runner)
        self.assertFalse(any(call[:2]==("systemctl","stop") for call in self.calls))

    def test_no_update_skips_service_and_backup(self):
        def runner(*args,cwd=None):
            value=self.runner(*args,cwd=cwd)
            return "old" if args==("git","rev-parse","FETCH_HEAD") else value
        result=upgrade(self.root,db_path=self.db,runner=runner)
        self.assertFalse(result["updated"])
        self.assertFalse(any(call[0]=="systemctl" for call in self.calls))

    def test_rejects_non_fast_forward(self):
        def runner(*args,cwd=None):
            value=self.runner(*args,cwd=cwd)
            return "different" if args==("git","merge-base","old","new") else value
        with self.assertRaisesRegex(ValueError,"fast-forward"):
            upgrade(self.root,db_path=self.db,runner=runner)
        self.assertFalse(any(call[0]=="systemctl" for call in self.calls))

    def test_rejects_wrong_branch(self):
        def runner(*args,cwd=None):
            value=self.runner(*args,cwd=cwd)
            return "experiment" if args==("git","branch","--show-current") else value
        with self.assertRaisesRegex(ValueError,"develop"):
            upgrade(self.root,db_path=self.db,runner=runner)

    def test_database_group_init_and_doctor(self):
        config=self.root/"config"
        config.mkdir()
        (config/"settings.json").write_text(json.dumps({"daemon":{"database_path":str(self.root/"new.db")}}))
        (config/"secrets.json").write_text("{}")
        with patch("builtins.print"):
            cli.main(["--config-dir",str(config),"database","init"])
            cli.main(["--config-dir",str(config),"database","doctor"])
        self.assertTrue((self.root/"new.db").is_file())


if __name__=="__main__":
    unittest.main()
