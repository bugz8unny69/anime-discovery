"""Tests for safe individual secret updates and redacted CLI settings output."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_admin_secret_editor import set_secret
from anime_admin_show import render
import anime_dashboard_auth as auth

class SecretEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        (self.path/"settings.json").write_text("{}")
        (self.path/"secrets.json").write_text(json.dumps({"web_token":"existing-webhook"}))
        os.chmod(self.path/"secrets.json",0o600)
        swap=patch.object(auth,"AUTH_FILE",self.path/"auth.json")
        swap.start()
        self.addCleanup(swap.stop)

    def test_blank_preserves_secret(self):
        previous=(self.path/"secrets.json").read_bytes()
        report=set_secret(self.path,"web_token",prompt=lambda _: "")
        self.assertFalse(report["changed"])
        self.assertEqual((self.path/"secrets.json").read_bytes(),previous)

    def test_replace_and_clear_requires_confirmation(self):
        report=set_secret(self.path,"ntfy_token",prompt=lambda _: "new-secret")
        self.assertTrue(report["changed"])
        self.assertEqual(json.loads((self.path/"secrets.json").read_text())["ntfy_token"],"new-secret")
        self.assertFalse(set_secret(self.path,"ntfy_token",clear=True,confirm=lambda _:"no")["changed"])
        self.assertTrue(set_secret(self.path,"ntfy_token",clear=True,confirm=lambda _:"CLEAR")["changed"])
        self.assertNotIn("ntfy_token",json.loads((self.path/"secrets.json").read_text()))

    def test_show_never_includes_credentials(self):
        out=render(self.path)
        self.assertIn("web_token",out)
        self.assertIn("Set",out)
        self.assertNotIn("existing-webhook",out)
        machine=json.loads(render(self.path,as_json=True))
        self.assertEqual(machine["credentials"]["web_token"],"Set")
        self.assertNotIn("existing-webhook",json.dumps(machine))

    def test_password_is_hashed_not_written_to_secrets(self):
        result=set_secret(self.path,"admin_password",prompt=lambda _:"a-new-strong-password")
        self.assertTrue(result["changed"])
        self.assertTrue(auth.verify("admin","a-new-strong-password"))
        self.assertNotIn("admin_password",json.loads((self.path/"secrets.json").read_text()))

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            set_secret(self.path,"unknown",prompt=lambda _:"unused")

if __name__=="__main__":
    unittest.main()
