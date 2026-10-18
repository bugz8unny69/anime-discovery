import unittest
from anime_identity_mapping_v4 import mappings, evaluate

XML = b'''<anime-list><anime anidbid="17495" tvdbid="389597" defaulttvdbseason="1" episodeoffset="0"/><anime anidbid="123" tvdbid="456"/></anime-list>'''
BASE = {'issues': [], 'crosscheck_v3': [
    {'anidb_id': '17495', 'tvdb_id': '389597', 'media_type': 'ANIMATION', 'title_corroborated': True},
    {'anidb_id': '17495', 'tvdb_id': '465668', 'media_type': 'UNKNOWN', 'title_corroborated': True},
]}

class MappingTests(unittest.TestCase):
    def test_exact_mapping(self):
        self.assertEqual(mappings(XML, '17495')[0]['tvdbid'], '389597')
    def test_no_other_mapping(self):
        self.assertEqual(mappings(XML, '999'), [])
    def test_corroboration_not_approval(self):
        result = evaluate(BASE, XML)
        self.assertIn('INDEPENDENT_MAPPING_CORROBORATED', result['next_action'])
        self.assertFalse(result['verified_identity'])
        self.assertFalse(result['usable_for_automation'])
    def test_live_action_conflict(self):
        bad = {'issues': [], 'crosscheck_v3': [{'anidb_id': '17495', 'tvdb_id': '389597', 'media_type': 'LIVE_ACTION', 'title_corroborated': True}]}
        self.assertIn('MAPPING_CONFLICT', evaluate(bad, XML)['next_action'])
    def test_unexpected_root(self):
        with self.assertRaises(ValueError):
            mappings(b'<wrong/>', '17495')

if __name__ == '__main__':
    unittest.main()
