"""First-install adoption tests; no systemd or VM privileges required."""
import importlib.util
import json
import os
import pwd
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_flat_config import DEFAULT_SETTINGS

spec=importlib.util.spec_from_file_location("anime_install",Path(__file__).resolve().parents[2]/"deploy"/"install-homelab.py")
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class AdoptExistingConfigTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.config=self.root/"etc"
        self.config.mkdir()
        self.data=self.root/"var"
        self.data.mkdir()
        self.account=pwd.getpwuid(os.getuid())
        old={"storage":{"download_root":str(self.root/"downloads"),
                        "trial_root":str(self.root/"Anime-Trial")},
             "daemon":{"database_path":str(self.data/"new.db"),"concurrency":7},
             "qbittorrent":{"base_url":"http://qb.local:8080","username":"old-user"}}
        (self.root/"downloads").mkdir()
        (self.root/"Anime-Trial").mkdir()
        (self.config/"settings.json").write_text(json.dumps(old))
        (self.config/"secrets.json").write_text(json.dumps({
            "web_token":"original-web-token","qbittorrent_password":"original-pass"}))
        os.chmod(self.config/"secrets.json",0o600)
        self.secrets_bytes=(self.config/"secrets.json").read_bytes()
        self.patch=patch.object(installer,"CONFIG_DIR",self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_adopts_settings_without_overwriting_storage_and_secrets(self):
        with patch.object(installer,"ask",return_value="yes"):
            config=installer._existing_setup(self.account)
        self.assertEqual(config["settings"]["daemon"]["concurrency"],7)
        self.assertEqual(config["settings"]["storage"]["trial_root"],
                         str(self.root/"Anime-Trial"))
        self.assertFalse(config["settings"]["prowlarr"]["enabled"])
        self.assertEqual(config["secrets"]["web_token"],"original-web-token")
        self.assertEqual((self.config/"secrets.json").read_bytes(),self.secrets_bytes)
        self.assertEqual(len(list(self.config.glob("settings.json.before-migrate-*.bak"))),1)
        target=installer._validate_install_settings(config)
        self.assertEqual(target,self.data/"new.db")
        from anime_fresh_database import initialize
        initialize(target)
        with self.assertRaises(FileExistsError):
            installer._validate_install_settings(config)

    def test_existing_config_decline_leaves_files_intact(self):
        prior=(self.config/"settings.json").read_bytes()
        with patch.object(installer,"ask",return_value="no"):
            with self.assertRaisesRegex(ValueError,"declined"):
                installer._existing_setup(self.account)
        self.assertEqual((self.config/"settings.json").read_bytes(),prior)
        self.assertEqual((self.config/"secrets.json").read_bytes(),self.secrets_bytes)

    def test_missing_secrets_refuses_half_install(self):
        (self.config/"secrets.json").unlink()
        with self.assertRaisesRegex(ValueError,"Both existing"):
            installer._existing_setup(self.account)

    def test_existing_config_invalid_paths_are_rejected_not_reset(self):
        with patch.object(installer,"ask",return_value="yes"):
            config=installer._existing_setup(self.account)
        config["settings"]["storage"]["trial_root"]=str(self.root/"missing")
        with self.assertRaisesRegex(ValueError,"storage paths"):
            installer._validate_install_settings(config)


if __name__=="__main__":
    unittest.main()
