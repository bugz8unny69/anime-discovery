import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_identity_evidence import evidence

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'mapping.json'
        self.cache = Path(self.tmp.name) / 'titles.gz'
        self.cache.write_bytes(gzip.compress(b'<animetitles><anime aid="12"><title>Example Anime</title></anime></animetitles>'))
    def put(self, data): self.path.write_text(json.dumps(data))
    def test_no_mapping(self):
        self.assertEqual(evidence(self.path, self.cache)['records'], [])
    def test_anidb_only_never_authorizes(self):
        self.put({'3': {'anidb_id': '12', 'tvdb_id': '34'}})
        result = evidence(self.path, self.cache)
        self.assertTrue(result['records'][0]['anidb_found'])
        self.assertFalse(result['usable_for_automation'])
    def test_title_overlap_still_requires_review(self):
        self.put({'3': {'anidb_id': '12', 'tvdb_id': '34'}})
        with patch('anime_identity_evidence.tvdb_token', return_value='token'), patch('anime_identity_evidence.tvdb_series', return_value={'id':'34','titles':['Example Anime'],'year':'2020'}):
            result = evidence(self.path, self.cache, tvdb_key='not-a-real-key')
        self.assertEqual(result['records'][0]['status'], 'TITLE_CORROBORATED_REVIEW_REQUIRED')
        self.assertFalse(result['records'][0]['usable_for_automation'])
    def test_conflict_fails_closed(self):
        self.put({'3': {'anidb_id':'12','tvdb_id':'34'}, '4': {'anidb_id':'12','tvdb_id':'35'}})
        result = evidence(self.path, self.cache)
        self.assertTrue(result['issues'])
        self.assertEqual(result['records'], [])
    def test_unsafe_flag_fails_closed(self):
        self.put({'3': {'anidb_id':'12','tvdb_id':'34','usable_for_automation':True}})
        self.assertTrue(evidence(self.path, self.cache)['issues'])
if __name__ == '__main__': unittest.main()
