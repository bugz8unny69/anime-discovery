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

    def test_storage_modes_are_validated_and_optional(self):
        self.assertEqual(load_config(self.path)["settings"]["storage"]["staged_directory_mode"],"2770")
        self.assertEqual(load_config(self.path)["settings"]["storage"]["staged_file_mode"],"0640")
        self.write({"storage":{"staged_directory_mode":"2775",
                               "staged_file_mode":"0660"}},{})
        storage=load_config(self.path)["settings"]["storage"]
        self.assertEqual((storage["staged_directory_mode"],storage["staged_file_mode"]),("2775","0660"))
        for section in ({"staged_directory_mode":"0640"},{"staged_file_mode":"2770"},
                        {"staged_directory_mode":"not-octal"}):
            self.write({"storage":section},{})
            with self.assertRaises(ValueError):
                load_config(self.path)

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
