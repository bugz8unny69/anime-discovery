"""Fresh v7 credential separation and safe updates; no runtime migration."""
import json
from pathlib import Path
import tempfile
import unittest

from src.nextgen.secrets import SecretStore, SecretStorageError
from src.nextgen.configuration_schema import ConfigurationConflict


class ApiAccessSecretsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SecretStore(self.root)

    def raw(self):
        return json.loads((self.root / "secrets.json").read_text())

    def test_fresh_install_has_no_management_token(self):
        self.store.initialize("provider-key", qbittorrent_username="user",
                              qbittorrent_password="pass")
        self.assertEqual(self.raw()["schema_version"], 8)
        self.assertNotIn("management_token", self.raw()["credentials"])
        self.assertFalse(self.store.status().management_configured)
        result = self.store.update_webhook_token("w" * 43, expected_revision=1)
        self.assertTrue(result.status.webhook_configured)
        self.assertEqual(self.raw()["schema_version"], 8)
        self.assertEqual(self.store.access_credentials().webhook_token, "w" * 43)
        self.assertNotIn("w" * 43, repr(self.store.status()))
        self.assertNotIn("w" * 43, repr(self.store.access_credentials()))

    def test_provider_credentials_survive_webhook_rotation(self):
        self.store.initialize("provider-key", webhook_token="w" * 43)
        self.store.update_webhook_token("x" * 43, expected_revision=1)
        self.assertEqual(self.store.tvdb_credentials().api_key, "provider-key")

    def test_fresh_install_refuses_obsolete_management_token(self):
        with self.assertRaises(SecretStorageError):
            self.store.initialize(webhook_token='w' * 43, management_token='m' * 43)
        self.assertFalse((self.root / 'secrets.json').exists())

    def test_stale_revision_invalid_values_and_permissions_fail_closed(self):
        self.store.initialize(webhook_token="w" * 43)
        with self.assertRaises(ConfigurationConflict):
            self.store.update_webhook_token("x" * 43, expected_revision=2)
        with self.assertRaises(SecretStorageError):
            self.store.update_webhook_token("short", expected_revision=1)
        with self.assertRaises(SecretStorageError):
            self.store.update_access_tokens("x" * 43, "m" * 43, expected_revision=1)
        (self.root / "secrets.json").chmod(0o644)
        with self.assertRaises(SecretStorageError):
            self.store.access_credentials()


if __name__ == "__main__":
    unittest.main()
