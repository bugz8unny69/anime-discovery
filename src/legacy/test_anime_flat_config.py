import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_flat_config import load_config

class FlatConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.write({"shoko":{"enabled":True,"auto_link_verified":True}},{"shoko_api_key":"test"})

    def write(self,settings,secrets):
        (self.path/"settings.json").write_text(json.dumps(settings))
        p=self.path/"secrets.json"
        p.write_text(json.dumps(secrets))
        os.chmod(p,0o600)

    def test_reads_separate_files(self):
        result=load_config(self.path)
        self.assertTrue(result["settings"]["shoko"]["auto_link_verified"])
        self.assertEqual(result["secrets"]["shoko_api_key"],"test")
        self.assertFalse(result["settings"]["qbittorrent"]["manage_download_limit"])

    def test_rejects_unsupported_priority(self):
        self.write({"qbittorrent":{"priority_mode":"high"}},{})
        with self.assertRaises(ValueError):
            load_config(self.path)

    def test_rejects_public_secrets(self):
        os.chmod(self.path/"secrets.json",0o644)
        with self.assertRaises(PermissionError):
            load_config(self.path)

if __name__=="__main__":
    unittest.main()
