import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import api_client

class ClientTests(unittest.TestCase):
    def test_token_file_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'secrets.json').write_text(json.dumps({'controller.api_token':'from-file'}))
            with patch.object(api_client, 'CONFIG_DIR', Path(d)), patch.dict(os.environ, {'ANIME_DISCOVERY_TOKEN':'from-env'}):
                self.assertEqual(api_client.load_token('controller'), 'from-file')
    def test_env_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(api_client, 'CONFIG_DIR', Path(d)), patch.dict(os.environ, {'ANIME_DISCOVERY_TOKEN':'legacy'}):
                self.assertEqual(api_client.load_token('controller'), 'legacy')
    def test_reject_external_url(self):
        with self.assertRaises(ValueError):
            api_client.request('controller', 'GET', '//example.com')
    def test_mutation_requires_yes(self):
        with self.assertRaises(SystemExit) as error:
            api_client.main(['controller', 'api', 'delete', '/series/1'])
        self.assertEqual(error.exception.code, 2)

if __name__ == '__main__': unittest.main()
