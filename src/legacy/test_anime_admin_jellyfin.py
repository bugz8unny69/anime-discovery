import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_admin_jellyfin import configure_jellyfin
from anime_flat_config import load_config

class JellyfinAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        (self.dir/"settings.json").write_text(json.dumps({"storage":{"download_root":"/tmp/downloads","trial_root":"/tmp/trial"}}))
        (self.dir/"secrets.json").write_text(json.dumps({"web_token":"token","qbittorrent_password":"keep"}))
        os.chmod(self.dir/"secrets.json",0o600)

    def test_configure_jellyfin_preserves_existing_secrets(self):
        result=configure_jellyfin(self.dir,ask=lambda _: "https://jellyfin.example.test",
                                 secret_prompt=lambda _: "jellyfin-secret")
        self.assertTrue(result["restart_required"])
        config=load_config(self.dir)
        self.assertTrue(config["settings"]["jellyfin"]["enabled"])
        self.assertEqual(config["settings"]["jellyfin"]["base_url"],"https://jellyfin.example.test")
        self.assertEqual(config["secrets"]["qbittorrent_password"],"keep")
        self.assertEqual(config["secrets"]["jellyfin_api_key"],"jellyfin-secret")
        self.assertEqual((self.dir/"secrets.json").stat().st_mode & 0o777,0o600)

    def test_invalid_url_does_not_change_files(self):
        old=(self.dir/"secrets.json").read_bytes()
        with self.assertRaises(ValueError):
            configure_jellyfin(self.dir,ask=lambda _: "file:///etc/passwd",secret_prompt=lambda _: "secret")
        self.assertEqual((self.dir/"secrets.json").read_bytes(),old)

if __name__=="__main__":
    unittest.main()
