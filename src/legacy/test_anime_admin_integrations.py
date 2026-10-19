"""Admin integration settings never erase unrelated secrets."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_admin_integrations import configure
from anime_flat_config import DEFAULT_SETTINGS,load_config

class ConfigureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        (self.dir/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
        (self.dir/"secrets.json").write_text(json.dumps({"web_token":"test","admin_password":"different","qbittorrent_password":"preserve"}))
        (self.dir/"secrets.json").chmod(0o600)
    def test_sonarr_preserves_other_secrets(self):
        answers=iter(["https://sonarr.example","/mnt/media/Anime","Anime","4","yes"])
        result=configure(self.dir,"sonarr",ask=lambda prompt:next(answers),secret_prompt=lambda prompt:"new-api-key")
        self.assertTrue(result["enabled"])
        cfg=load_config(self.dir)
        self.assertEqual(cfg["secrets"]["qbittorrent_password"],"preserve")
        self.assertEqual(cfg["secrets"]["sonarr_api_key"],"new-api-key")
        self.assertEqual(cfg["settings"]["sonarr"]["quality_profile_id"],4)
        self.assertEqual((self.dir/"secrets.json").stat().st_mode & 0o777,0o600)
    def test_invalid_config_does_not_modify_files(self):
        before=(self.dir/"settings.json").read_bytes(),(self.dir/"secrets.json").read_bytes()
        answers=iter(["http://insecure.example","topic","https://anime.example","24","yes"])
        with self.assertRaises(ValueError):
            configure(self.dir,"ntfy",ask=lambda prompt:next(answers),secret_prompt=lambda prompt:"")
        self.assertEqual(before,((self.dir/"settings.json").read_bytes(),(self.dir/"secrets.json").read_bytes()))

if __name__=="__main__": unittest.main()
