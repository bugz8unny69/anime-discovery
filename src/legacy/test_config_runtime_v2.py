import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from anime_config_runtime import get

class ConfigRuntimeTests(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}, clear=True):
            self.assertFalse(get('tvdb.enabled'))
            self.assertEqual(get('discovery.max_trial_episodes'),6)
    def test_env_fallback_and_file_override(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp,'ANIME_TVDB_API_KEY':'legacy'}, clear=True):
            self.assertEqual(get('tvdb.api_key'),'legacy')
            Path(tmp,'secrets.json').write_text(json.dumps({'tvdb.api_key':'saved'}))
            self.assertEqual(get('tvdb.api_key'),'saved')
    def test_hot_reload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}, clear=True):
            p=Path(tmp,'config.json')
            p.write_text('{"tvdb.enabled": false}')
            self.assertFalse(get('tvdb.enabled'))
            p.write_text('{"tvdb.enabled": true}')
            self.assertTrue(get('tvdb.enabled'))
    def test_invalid_setting_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}, clear=True):
            Path(tmp,'config.json').write_text('{"discovery.max_trial_episodes": 100}')
            with self.assertRaises(ValueError):get('discovery.max_trial_episodes')
if __name__=='__main__':unittest.main()
