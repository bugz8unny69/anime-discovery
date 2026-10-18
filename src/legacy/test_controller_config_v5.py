import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import json
from anime_config_runtime import get
from api import trial_limit, LIMIT

class ControllerConfigTests(unittest.TestCase):
    def test_default_six(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}):
            self.assertEqual(trial_limit(), 6)
    def test_change_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}):
            p=Path(tmp)/'config.json'
            p.write_text(json.dumps({'discovery.max_trial_episodes':3}))
            self.assertEqual(trial_limit(), 3)
            p.write_text(json.dumps({'discovery.max_trial_episodes':5}))
            self.assertEqual(trial_limit(), 5)
    def test_above_six_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}):
            (Path(tmp)/'config.json').write_text(json.dumps({'discovery.max_trial_episodes':7}))
            with self.assertRaises(ValueError): trial_limit()
    def test_downloads_stay_disabled(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ANIME_CONFIG_DIR':tmp}):
            self.assertFalse(get('discovery.downloads_enabled'))
            self.assertEqual(LIMIT,6)
if __name__=='__main__': unittest.main()
