import copy
import json
import unittest
from pathlib import Path
from anime_episode_confidence_v13 import evaluate

FIXTURE = json.loads((Path(__file__).parent / 'v13-solo-leveling-fixture.json').read_text())

class ConfidenceTests(unittest.TestCase):
    def test_solo_leveling_shadow(self):
        x = evaluate(FIXTURE)
        self.assertEqual(x['score_points'], 90)
        self.assertTrue(x['would_approve_episode_mapping'])
        self.assertFalse(x['episode_identity_verified'])
        self.assertFalse(x['eligible_for_acquisition'])
    def test_api_issues_block(self):
        x = copy.deepcopy(FIXTURE); x['issues'] = ['TIMEOUT']
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_special_blocks(self):
        x = copy.deepcopy(FIXTURE); x['release_name'] += ' OVA'
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_season_two_blocks(self):
        x = copy.deepcopy(FIXTURE); x['release_name'] += ' Season 2'
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_override_blocks(self):
        x = copy.deepcopy(FIXTURE); x['episode_audit'][0]['episode_specific_rules'] = ['custom']
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_conflicting_id_blocks(self):
        x = copy.deepcopy(FIXTURE); x['episode_audit'][0]['tvdb_id'] = '999'
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_no_episode_record_blocks(self):
        x = copy.deepcopy(FIXTURE); x['tvdb_episode_checks'] = []
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_nonzero_offset_blocks(self):
        x = copy.deepcopy(FIXTURE); x['episode_audit'][0]['episode_offset'] = 12
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])
    def test_duplicate_mapping_blocks(self):
        x = copy.deepcopy(FIXTURE); x['mapping_evidence'].append(copy.deepcopy(x['mapping_evidence'][2]))
        self.assertFalse(evaluate(x)['would_approve_episode_mapping'])

if __name__ == '__main__': unittest.main()
