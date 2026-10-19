"""Migration preserves existing values and secrets, with preview and backup."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from anime_admin_config_migration import migrate
from anime_flat_config import load_config


class ExistingSettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory=Path(tmp.name)
        self.settings=self.directory/"settings.json"
        self.secrets=self.directory/"secrets.json"
        self.settings.write_text(json.dumps({
            "daemon":{"database_path":"/srv/existing/anime.sqlite","concurrency":7},
            "storage":{"download_root":"/mnt/old-download","trial_root":"/mnt/Anime-Trial"},
            "qbittorrent":{"base_url":"https://my-qb.example","username":"existing"}}))
        self.secrets.write_text(json.dumps({
            "web_token":"DO-NOT-REPLACE","qbittorrent_password":"EXISTING-PASSWORD"}))
        os.chmod(self.secrets,0o600)
        self.before_settings=self.settings.read_bytes()
        self.before_secrets=self.secrets.read_bytes()
        self.before_secret_mode=self.secrets.stat().st_mode&0o777

    def test_preview_is_read_only_and_lists_new_settings(self):
        report=migrate(self.directory)
        self.assertTrue(report["ready"])
        self.assertFalse(report["changed"])
        self.assertIn("prowlarr.enabled",report["missing_settings"])
        self.assertIn("identity.series_map",report["missing_settings"])
        self.assertEqual(self.settings.read_bytes(),self.before_settings)
        self.assertEqual(self.secrets.read_bytes(),self.before_secrets)
        self.assertNotIn("DO-NOT-REPLACE",json.dumps(report))

    def test_apply_preserves_paths_existing_values_and_secrets(self):
        report=migrate(self.directory,apply=True)
        self.assertTrue(report["changed"])
        self.assertTrue(Path(report["backup"]).is_file())
        self.assertEqual(Path(report["backup"]).read_bytes(),self.before_settings)
        result=load_config(self.directory)
        self.assertEqual(result["settings"]["storage"]["trial_root"],"/mnt/Anime-Trial")
        self.assertEqual(result["settings"]["daemon"]["database_path"],"/srv/existing/anime.sqlite")
        self.assertEqual(result["settings"]["daemon"]["concurrency"],7)
        self.assertEqual(result["settings"]["qbittorrent"]["base_url"],"https://my-qb.example")
        self.assertFalse(result["settings"]["prowlarr"]["enabled"])
        self.assertEqual(result["settings"]["identity"]["series_map"],{})
        self.assertEqual(self.secrets.read_bytes(),self.before_secrets)
        self.assertEqual(self.secrets.stat().st_mode&0o777,self.before_secret_mode)
        second=migrate(self.directory,apply=True)
        self.assertFalse(second["changed"])
        self.assertIsNone(second["backup"])

    def test_upgrade_migration_adds_integrations_without_replacing_credentials(self):
        """Rehearse existing-install upgrade -> settings migrate --apply."""
        original=json.loads(self.settings.read_text())
        original["sonarr"]={"enabled":True,"base_url":"https://sonarr.local",
                            "root_folder":"/mnt/media/Anime",
                            "quality_profile_name":"Anime","quality_profile_id":8}
        original["shoko"]={"enabled":True,"base_url":"https://shoko.local"}
        original["tvdb"]={"enabled":True}
        original["ntfy"]={"enabled":True,"server":"https://ntfy.local",
                           "topic":"anime","dashboard_url":"https://dashboard.local"}
        self.settings.write_text(json.dumps(original))
        credentials=json.loads(self.secrets.read_text())
        credentials.update({"sonarr_api_key":"SONARR-KEEP","shoko_api_key":"SHOKO-KEEP",
                            "tvdb_api_key":"TVDB-KEEP","ntfy_token":"NTFY-KEEP",
                            "admin_password":"ADMIN-KEEP"})
        self.secrets.write_text(json.dumps(credentials))
        before=self.secrets.read_bytes()
        preview=migrate(self.directory)
        self.assertTrue(preview["ready"])
        self.assertIn("shoko.poll_seconds",preview["missing_settings"])
        self.assertEqual(self.secrets.read_bytes(),before)
        migrated=migrate(self.directory,apply=True)
        self.assertTrue(migrated["changed"])
        result=load_config(self.directory)
        self.assertEqual(result["settings"]["sonarr"]["quality_profile_id"],8)
        self.assertEqual(result["settings"]["shoko"]["base_url"],"https://shoko.local")
        self.assertEqual(result["settings"]["ntfy"]["server"],"https://ntfy.local")
        self.assertEqual(result["settings"]["tvdb"]["enabled"],True)
        self.assertEqual(result["secrets"]["sonarr_api_key"],"SONARR-KEEP")
        self.assertEqual(result["secrets"]["shoko_api_key"],"SHOKO-KEEP")
        self.assertEqual(result["secrets"]["tvdb_api_key"],"TVDB-KEEP")
        self.assertEqual(result["secrets"]["ntfy_token"],"NTFY-KEEP")
        self.assertEqual(result["secrets"]["web_token"],"DO-NOT-REPLACE")
        self.assertEqual(self.secrets.read_bytes(),before)
        self.assertFalse(migrate(self.directory,apply=True)["changed"])

    def test_unknown_keys_are_reported_and_block_apply_without_data_loss(self):
        value=json.loads(self.settings.read_text())
        value["legacy_section"]={"special_path":"/keep/me"}
        self.settings.write_text(json.dumps(value))
        previous=self.settings.read_bytes()
        report=migrate(self.directory)
        self.assertIn("legacy_section",report["unknown_settings"])
        self.assertFalse(report["ready"])
        with self.assertRaisesRegex(ValueError,"Unknown legacy keys"):
            migrate(self.directory,apply=True)
        self.assertEqual(self.settings.read_bytes(),previous)
        self.assertEqual(self.secrets.read_bytes(),self.before_secrets)

    def test_invalid_existing_settings_are_not_overwritten(self):
        value=json.loads(self.settings.read_text())
        value["daemon"]["concurrency"]=-1
        self.settings.write_text(json.dumps(value))
        previous=self.settings.read_bytes()
        with self.assertRaises(ValueError):
            migrate(self.directory,apply=True)
        self.assertEqual(self.settings.read_bytes(),previous)
        self.assertEqual(self.secrets.read_bytes(),self.before_secrets)

    def test_refuses_symlinked_settings_or_secrets(self):
        original=self.directory/"real-secrets.json"
        self.secrets.rename(original)
        self.secrets.symlink_to(original)
        with self.assertRaises(ValueError):
            migrate(self.directory,apply=True)
        self.assertEqual(original.read_bytes(),self.before_secrets)


if __name__=="__main__":
    unittest.main()
