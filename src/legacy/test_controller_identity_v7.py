import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import api

class IdentityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'identity.json'
        self.env = patch.dict(os.environ, {'ANIME_IDENTITY_MAPPINGS': str(self.path)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_catalog(self):
        result = api.list_identity_suggestions()
        self.assertEqual(result['records'], [])
        self.assertFalse(result['usable_for_automation'])

    def test_manual_mapping_stays_untrusted(self):
        self.path.write_text(json.dumps({'3': {'anidb_id': '12345', 'tvdb_id': '123456', 'verification': 'USER_PROVIDED_UNVERIFIED'}}))
        result = api.list_identity_suggestions()
        self.assertEqual(result['records'][0]['review_id'], '3')
        self.assertFalse(result['records'][0]['usable_for_automation'])

    def test_conflict_fails_closed(self):
        self.path.write_text(json.dumps({'3': {'anidb_id': '12345', 'tvdb_id': '123456'}, '4': {'anidb_id': '12345', 'tvdb_id': '999'}}))
        with self.assertRaises(api.HTTPException) as cm:
            api.list_identity_suggestions()
        self.assertEqual(cm.exception.status_code, 409)

    def test_unsafe_flag_fails_closed(self):
        self.path.write_text(json.dumps({'3': {'anidb_id': '12345', 'tvdb_id': '123456', 'usable_for_automation': True}}))
        with self.assertRaises(api.HTTPException) as cm:
            api.list_identity_suggestions()
        self.assertEqual(cm.exception.status_code, 409)

if __name__ == '__main__':
    unittest.main()
