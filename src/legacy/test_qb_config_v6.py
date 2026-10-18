import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# Stub the network adapter; tests never access qBittorrent.
adapter = types.ModuleType('qb_trial_add_adapter')
adapter.validate_magnet = lambda *args: None
adapter.QBTrialAdd = object
sys.modules['qb_trial_add_adapter'] = adapter
import anime_trial_operator as operator

class ConfigTests(unittest.TestCase):
    def test_saved_credentials_override_environment(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'config.json').write_text(json.dumps({'qbittorrent.username':'stored-user'}))
            Path(d, 'secrets.json').write_text(json.dumps({'qbittorrent.password':'stored-password'}))
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR':d, 'ANIME_QB_USERNAME':'old-user', 'ANIME_QB_PASSWORD':'old-password'}):
                with patch.object(operator, 'QBTrialAdd') as qb:
                    operator.client()
                    qb.assert_called_once_with('http://127.0.0.1:8080','stored-user','stored-password')
                    qb.return_value.login.assert_called_once()

    def test_environment_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR':d, 'ANIME_QB_USERNAME':'fallback-user','ANIME_QB_PASSWORD':'fallback-password'}):
                with patch.object(operator, 'QBTrialAdd') as qb:
                    operator.client()
                    qb.assert_called_once_with('http://127.0.0.1:8080','fallback-user','fallback-password')

    def test_missing_password_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR':d}, clear=True):
                with self.assertRaises(RuntimeError):
                    operator.client()

    def test_credentials_reread_each_client(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'config.json').write_text('{"qbittorrent.username":"user"}')
            secret = Path(d,'secrets.json')
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR':d}, clear=True):
                with patch.object(operator, 'QBTrialAdd') as qb:
                    secret.write_text('{"qbittorrent.password":"first-password"}')
                    operator.client()
                    secret.write_text('{"qbittorrent.password":"second-password"}')
                    operator.client()
                    self.assertEqual(qb.call_args_list[0].args[-1], 'first-password')
                    self.assertEqual(qb.call_args_list[1].args[-1], 'second-password')

if __name__ == '__main__': unittest.main()
