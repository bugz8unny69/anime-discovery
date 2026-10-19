"""Offline tests for the authoritative dashboard password and session store."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import anime_dashboard_auth as auth

class DashboardAuthTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        swap=patch.object(auth,"AUTH_FILE",Path(tmp.name)/"auth.json")
        swap.start()
        self.addCleanup(swap.stop)

    def test_legacy_password_migrates_once(self):
        self.assertTrue(auth.initialize_legacy("short-old"))
        self.assertTrue(auth.verify("admin","short-old"))
        self.assertFalse(auth.initialize_legacy("different"))
        self.assertTrue(auth.verify("admin","short-old"))
        self.assertNotIn("short-old",auth.AUTH_FILE.read_text())
        self.assertEqual(auth.AUTH_FILE.stat().st_mode & 0o777,0o600)

    def test_password_rotation_revokes_sessions(self):
        auth.set_password("first-strong-password")
        old=auth.session_token(ttl=1000)
        self.assertTrue(auth.valid_session(old))
        self.assertTrue(auth.verify("admin","first-strong-password"))
        auth.set_password("second-strong-password")
        self.assertFalse(auth.verify("admin","first-strong-password"))
        self.assertTrue(auth.verify("admin","second-strong-password"))
        self.assertFalse(auth.valid_session(old))

    def test_expiry_rejected(self):
        auth.set_password("first-strong-password")
        self.assertFalse(auth.valid_session(auth.session_token(ttl=-1)))
        self.assertFalse(auth.valid_session("malformed"))

if __name__=="__main__":
    unittest.main()
