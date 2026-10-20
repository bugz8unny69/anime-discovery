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

    def test_dashboard_settings_apply_automatically_without_service_restart(self):
        report=apply_settings(self.path,{"anidb":{"client":"registeredclient","clientver":1}})
        self.assertTrue(report["saved"])
        self.assertFalse(report["restart_required"])
        self.assertEqual(report["apply_mode"],"automatic")
        self.assertFalse(report["runtime_applied"])
        report=apply_settings(self.path,{"jellyfin":{"write_trial_nfo":False,"enabled":False,"base_url":"https://jellyfin.test"}})
        # Internal and hidden switches are intentionally restart-classified.
        self.assertTrue(report["restart_required"])
        report=apply_settings(self.path,{"sonarr":{"quality_profile_name":"Dubbed"}})
        self.assertFalse(report["restart_required"])

    def test_invalid_batch_never_changes_file(self):
        before=(self.path/"settings.json").read_bytes()
        with self.assertRaises(ValueError):
            apply_settings(self.path,{"web":{"port":0},"daemon":{"concurrency":3}})
        self.assertEqual(before,(self.path/"settings.json").read_bytes())

    def test_anidb_http_client_persists_and_is_validated(self):
        saved=apply_settings(self.path,{"anidb":{"client":"registeredclient","clientver":2}})
        self.assertTrue(saved["saved"])
        self.assertIn("anidb.client",saved["changed"])
        self.assertEqual(snapshot(self.path)["settings"]["anidb"]["client"],"registeredclient")
        prior=(self.path/"settings.json").read_bytes()
        for invalid in ({"clientver":0},{"clientver":True},{"client":"invalid client name"}):
            with self.assertRaises(ValueError):
                apply_settings(self.path,{"anidb":invalid})
            self.assertEqual((self.path/"settings.json").read_bytes(),prior)

    def test_noop_is_not_restart(self):
        self.assertFalse(apply_settings(self.path,{"web":{"port":8765}})["restart_required"])

if __name__=="__main__":unittest.main()
