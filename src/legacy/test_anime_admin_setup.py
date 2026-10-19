import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import anime_dashboard_auth as auth
from anime_admin_setup import setup, initialized

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        (self.dir/"settings.json").write_text("{}")
        (self.dir/"secrets.json").write_text("{}")
        os.chmod(self.dir/"secrets.json",0o600)
        owner=patch.object(auth,"AUTH_FILE",self.dir/"auth.json")
        owner.start()
        self.addCleanup(owner.stop)

    def test_first_run_and_repeat_preserve_credentials(self):
        answers=iter(["","","n","n","n","n"])
        passwords=iter(["strong-password-123","strong-password-123"])
        report=setup(self.dir,ask=lambda _:next(answers),
                     password_prompt=lambda _:next(passwords))
        self.assertTrue(report["configured"])
        self.assertTrue(initialized(self.dir))
        self.assertTrue(auth.verify("admin","strong-password-123"))
        secrets=json.loads((self.dir/"secrets.json").read_text())
        self.assertTrue(secrets["web_token"])
        self.assertNotIn("strong-password-123",json.dumps(secrets))
        self.assertTrue(setup(self.dir)["unchanged"])

    def test_invalid_listener_is_atomic(self):
        original=(self.dir/"settings.json").read_bytes()
        with self.assertRaises(ValueError):
            setup(self.dir,ask=lambda _:"invalid" if "port" in _ else "")
        self.assertEqual((self.dir/"settings.json").read_bytes(),original)
        self.assertFalse(initialized(self.dir))

if __name__=="__main__":unittest.main()
