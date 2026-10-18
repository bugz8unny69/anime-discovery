import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import anime_library_sync as sync

class JellyfinConfigTests(unittest.TestCase):
    def test_file_settings_override_environment_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'config.json').write_text(json.dumps({'jellyfin.url': 'https://example.test'}))
            (p / 'secrets.json').write_text(json.dumps({'jellyfin.api_key': 'test-key'}))
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR': tmp, 'ANIME_JELLYFIN_URL': 'https://legacy.test', 'ANIME_JELLYFIN_API_KEY': 'old'}):
                with patch('urllib.request.urlopen') as urlopen:
                    urlopen.return_value.__enter__.return_value.status = 204
                    self.assertTrue(sync.scan())
                    req = urlopen.call_args.args[0]
                    self.assertEqual(req.full_url, 'https://example.test/Library/Refresh')
                    self.assertEqual(req.get_header('X-emby-token'), 'test-key')
                    (p / 'config.json').write_text(json.dumps({'jellyfin.url': 'https://new.test'}))
                    self.assertTrue(sync.scan())
                    self.assertEqual(urlopen.call_args.args[0].full_url, 'https://new.test/Library/Refresh')

    def test_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'ANIME_CONFIG_DIR': tmp, 'ANIME_JELLYFIN_URL': 'https://legacy.test', 'ANIME_JELLYFIN_API_KEY': 'old'}):
                with patch('urllib.request.urlopen') as urlopen:
                    urlopen.return_value.__enter__.return_value.status = 204
                    self.assertTrue(sync.scan())
                    self.assertEqual(urlopen.call_args.args[0].full_url, 'https://legacy.test/Library/Refresh')

if __name__ == '__main__':
    unittest.main()
