import unittest
from anime_episode_verification_v16 import verify

class TestVerification(unittest.TestCase):
    def setUp(self):
        self.report = {'notification_id': 7, 'release_name': 'Sample - 01', 'episode_candidate': 1,
            'mapping_evidence': [{'anime_lists_pair_match': True, 'anidb_id': 10, 'tvdb_id': 20,
                'media_type': 'ANIMATION', 'title_corroborated': True, 'anime_lists_records': [{}]}],
            'episode_audit': [{'anidb_id': 10, 'tvdb_id': 20, 'default_tvdb_season': 1,
                'episode_offset': 0, 'episode_candidate': 1, 'episode_specific_rules': [], 'audit_flags': []}],
            'tvdb_episode_checks': [{'tvdb_id': 20, 'candidate_episode': 1, 'season': 1,
                'tvdb_episode_exists_at_same_number': True, 'tvdb_episode_records': [{'id': 123}]}]}
        self.shadow = {'decision': 'SHADOW_HIGH_CONFIDENCE', 'score_points': 100, 'blockers': []}
    def test_explicit_zero_offset_verified(self):
        r = verify(self.report, self.shadow)
        self.assertEqual(r['decision'], 'AUTO_VERIFIED_CANDIDATE')
        self.assertTrue(r['episode_identity_verified'])
        self.assertFalse(r['eligible_for_acquisition'])
    def test_missing_offset_not_verified(self):
        self.report['episode_audit'][0]['episode_offset'] = None
        r = verify(self.report, self.shadow)
        self.assertFalse(r['episode_identity_verified'])
        self.assertEqual(r['decision'], 'AWAITING_MAPPING_EVIDENCE')
    def test_conflict_blocks(self):
        self.report['episode_audit'][0]['tvdb_id'] = 99
        self.assertFalse(verify(self.report, self.shadow)['episode_identity_verified'])
    def test_special_blocks(self):
        self.report['release_name'] = 'Sample OVA - 01'
        self.assertFalse(verify(self.report, self.shadow)['episode_identity_verified'])
    def test_policy_blocks(self):
        self.shadow['decision'] = 'SHADOW_MORE_EVIDENCE'
        self.assertFalse(verify(self.report, self.shadow)['episode_identity_verified'])
    def test_no_approval_or_acquisition(self):
        r = verify(self.report, self.shadow)
        self.assertFalse(r['write_approval_performed'])
        self.assertFalse(r['eligible_for_acquisition'])

if __name__ == '__main__':
    unittest.main()
