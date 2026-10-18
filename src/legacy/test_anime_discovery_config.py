import importlib
import tempfile
import unittest
from pathlib import Path
import anime_discovery as cfg

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = cfg.ROOT
        cfg.ROOT = Path(self.temp.name)
    def tearDown(self):
        cfg.ROOT = self.old
        self.temp.cleanup()
    def test_default(self):
        self.assertEqual(cfg.effective('discovery.max_trial_episodes'), (6, 'default'))
    def test_persistence(self):
        cfg.update('tvdb.enabled', 'true')
        self.assertEqual(cfg.effective('tvdb.enabled'), (True, 'file'))
        cfg.update('tvdb.enabled', unset=True)
        self.assertEqual(cfg.effective('tvdb.enabled'), (False, 'default'))
    def test_reject_unknown(self):
        with self.assertRaises(ValueError): cfg.update('evil.setting', 'yes')
    def test_limit(self):
        with self.assertRaises(ValueError): cfg.update('discovery.max_trial_episodes', '7')
    def test_secret_permissions(self):
        cfg.update('tvdb.api_key', 'dummy')
        self.assertEqual((cfg.ROOT/'secrets.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(cfg.effective('tvdb.api_key'), ('dummy', 'file'))

if __name__ == '__main__': unittest.main()
