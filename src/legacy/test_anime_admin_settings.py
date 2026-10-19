import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_admin_settings import set_setting

class AdminSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        (self.dir/"settings.json").write_text("{}")
        (self.dir/"secrets.json").write_text("{}")
        os.chmod(self.dir/"secrets.json",0o600)

    def test_atomic_update_preserves_json(self):
        self.assertEqual(set_setting(self.dir,"daemon.concurrency",3),3)
        self.assertEqual(json.loads((self.dir/"settings.json").read_text())["daemon"]["concurrency"],3)

    def test_invalid_value_does_not_modify_file(self):
        before=(self.dir/"settings.json").read_bytes()
        with self.assertRaises(ValueError):
            set_setting(self.dir,"daemon.concurrency",0)
        self.assertEqual((self.dir/"settings.json").read_bytes(),before)

    def test_unknown_setting_refused(self):
        with self.assertRaises(ValueError):
            set_setting(self.dir,"shoko.password","secret")

if __name__=="__main__":
    unittest.main()
