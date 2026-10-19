import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import anime_dashboard_auth as auth
from anime_shared_settings import apply_settings,snapshot

class SharedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        (self.path/"settings.json").write_text("{}")
        (self.path/"secrets.json").write_text('{"web_token":"test-secret"}')
        os.chmod(self.path/"secrets.json",0o600)
        swap=patch.object(auth,"AUTH_FILE",self.path/"auth.json")
        swap.start()
        self.addCleanup(swap.stop)

    def test_snapshot_redacts(self):
        data=snapshot(self.path)
        self.assertTrue(data["credential_status"]["web_token"])
        self.assertNotIn("test-secret",json.dumps(data))

    def test_batch_persists_and_requires_restart(self):
        data=apply_settings(self.path,{"web":{"port":9999},"daemon":{"concurrency":3}})
        self.assertTrue(data["saved"])
        self.assertTrue(data["restart_required"])
        self.assertFalse(data["runtime_applied"])
        self.assertEqual(snapshot(self.path)["settings"]["web"]["port"],9999)

    def test_invalid_batch_never_changes_file(self):
        before=(self.path/"settings.json").read_bytes()
        with self.assertRaises(ValueError):
            apply_settings(self.path,{"web":{"port":0},"daemon":{"concurrency":3}})
        self.assertEqual(before,(self.path/"settings.json").read_bytes())

    def test_noop_is_not_restart(self):
        self.assertFalse(apply_settings(self.path,{"web":{"port":8765}})["restart_required"])

if __name__=="__main__":unittest.main()
