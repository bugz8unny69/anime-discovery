"""Offline central secrets v3 compatibility and presence-only views; unexecuted."""
import json
from pathlib import Path
import tempfile
import unittest
from src.nextgen.secrets import SecretStore, SecretStorageError
from src.nextgen.configuration_schema import ConfigurationConflict


class ApiAccessSecretsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=SecretStore(self.root)
    def raw(self):return json.loads((self.root/'secrets.json').read_text())
    def test_explicit_v3_upgrade_preserves_provider_credentials_and_future_updates(self):
        self.store.initialize('provider-key',qbittorrent_username='user',qbittorrent_password='pass')
        self.assertEqual(self.raw()['schema_version'],2)
        result=self.store.update_access_tokens('w'*43,'m'*43,expected_revision=1)
        self.assertEqual(self.raw()['schema_version'],3)
        self.assertTrue(result.status.management_configured);self.assertTrue(result.status.webhook_configured)
        self.store.update_tvdb_api_key('new-provider',expected_revision=2)
        self.store.update_qbittorrent_credentials('new-user','new-pass',expected_revision=3)
        self.assertEqual(self.store.access_credentials().management_token,'m'*43)
        self.assertEqual(self.raw()['schema_version'],3)
        self.assertNotIn('m'*43,repr(self.store.access_credentials()))
        self.assertNotIn('w'*43,repr(self.store.status()))
    def test_sonarr_v4_upgrade_is_private_and_preserves_existing_credentials(self):
        self.store.initialize('tvdb-provider',qbittorrent_username='downloader',
                              qbittorrent_password='private-pass',webhook_token='w'*43,
                              management_token='m'*43)
        self.assertEqual(self.raw()['schema_version'],3)
        updated=self.store.update_sonarr_api_key('sonarr-private-key',expected_revision=1)
        self.assertEqual(self.raw()['schema_version'],4)
        self.assertTrue(updated.status.sonarr_configured)
        self.assertEqual(self.store.sonarr_api_key(),'sonarr-private-key')
        self.assertNotIn('sonarr-private-key',repr(self.store.status()))
        self.assertEqual(self.store.access_credentials().management_token,'m'*43)
        self.store.update_tvdb_api_key('tvdb-rotated',expected_revision=2)
        self.assertEqual(self.raw()['schema_version'],4)
        self.store.update_sonarr_api_key('',expected_revision=3)
        self.assertFalse(self.store.status().sonarr_configured)
        with self.assertRaises(SecretStorageError):self.store.sonarr_api_key()

    def test_missing_keys_are_blank_and_legacy_v1_reads_do_not_upgrade(self):
        self.assertEqual(self.store.access_credentials().webhook_token,'')
        path=self.root/'secrets.json'
        path.write_text(json.dumps({'schema_version':1,'revision':1,'credentials':{'tvdb_api_key':'key'}}));path.chmod(0o600)
        before=path.read_bytes()
        self.assertEqual(self.store.access_credentials().management_token,'')
        self.assertEqual(path.read_bytes(),before)
    def test_same_tokens_bad_values_permissions_and_stale_revision_fail_closed(self):
        with self.assertRaises(SecretStorageError):self.store.initialize(webhook_token='m'*43,management_token='m'*43)
        self.store.initialize(webhook_token='w'*43,management_token='m'*43)
        with self.assertRaises(ConfigurationConflict):self.store.update_access_tokens('x'*43,'y'*43,expected_revision=2)
        with self.assertRaises(SecretStorageError):self.store.update_access_tokens('short','y'*43,expected_revision=1)
        (self.root/'secrets.json').chmod(0o644)
        with self.assertRaises(SecretStorageError):self.store.access_credentials()
