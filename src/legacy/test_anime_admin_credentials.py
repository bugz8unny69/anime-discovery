import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_admin_credentials import configure_credentials
from anime_flat_config import load_config
from unittest.mock import patch
import anime_dashboard_auth as auth

class ConfigureCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.path=self.directory/"secrets.json"
        auth_patch=patch.object(auth,"AUTH_FILE",self.directory/"dashboard-auth.json")
        auth_patch.start()
        self.addCleanup(auth_patch.stop)
        self.path.write_text(json.dumps({"web_token":"old-webhook","qbittorrent_password":"existing"}))
        os.chmod(self.path,0o600)

    def test_add_admin_password_without_erasing_other_secrets(self):
        before=self.path.stat()
        entries=iter(["","different-admin"])
        report=configure_credentials(self.directory,prompt=lambda _:next(entries))
        self.assertFalse(report["restart_required"])
        actual=json.loads(self.path.read_text())
        self.assertEqual(actual["web_token"],"old-webhook")
        self.assertEqual(actual["qbittorrent_password"],"existing")
        self.assertNotIn("admin_password",actual)
        self.assertTrue(auth.verify("admin","different-admin"))
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.path.stat().st_uid,before.st_uid)

    def test_password_change_invalidates_existing_session(self):
        entries=iter(["","different-admin"])
        configure_credentials(self.directory,prompt=lambda _:next(entries))
        session=auth.session_token()
        entries=iter(["","another-strong-password"])
        configure_credentials(self.directory,prompt=lambda _:next(entries))
        self.assertFalse(auth.valid_session(session))
        self.assertFalse(auth.verify("admin","different-admin"))
        self.assertTrue(auth.verify("admin","another-strong-password"))

    def test_same_admin_password_refused_and_file_untouched(self):
        original=self.path.read_bytes()
        entries=iter(["","old-webhook"])
        with self.assertRaisesRegex(ValueError,"differ"):
            configure_credentials(self.directory,prompt=lambda _:next(entries))
        self.assertEqual(self.path.read_bytes(),original)

if __name__=="__main__":
    unittest.main()
