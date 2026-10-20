import unittest
from anime_identity_mapping_v4 import mappings, evaluate, resolve_episode

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
    def test_offset_and_explicit_rule_precedence(self):
        xml=b'''<anime-list><anime anidbid="1" tvdbid="2"
          defaulttvdbseason="1" episodeoffset="12">
          <mapping-list>
           <mapping anidbseason="1" tvdbseason="2" start="1" end="12" offset="-1"/>
           <mapping anidbseason="1" tvdbseason="3">;3-8;</mapping>
          </mapping-list></anime></anime-list>'''
        self.assertEqual(resolve_episode(xml,1,2,2)["tvdb_episode"],1)
        self.assertEqual((resolve_episode(xml,1,2,3)["tvdb_season"],
                          resolve_episode(xml,1,2,3)["tvdb_episode"]),(3,8))
        self.assertEqual(resolve_episode(xml,1,2,13)["tvdb_episode"],25)

    def test_unsafe_multi_episode_and_conflicting_rules_fail_closed(self):
        xml=b'''<anime-list><anime anidbid="1" tvdbid="2"
          defaulttvdbseason="1"><mapping-list>
          <mapping anidbseason="1" tvdbseason="1">;1-1+2;</mapping>
          </mapping-list></anime></anime-list>'''
        self.assertIsNone(resolve_episode(xml,1,2,1))
        self.assertIsNone(resolve_episode(xml,1,3,1))
        self.assertIsNone(resolve_episode(xml,1,2,0))

    def test_special_not_inferred_as_regular_episode(self):
        self.assertIsNone(resolve_episode(XML,17495,389597,1,anidb_season=0))

    def test_unexpected_root(self):
        with self.assertRaises(ValueError):
            mappings(b'<wrong/>', '17495')

if __name__ == '__main__':
    unittest.main()
