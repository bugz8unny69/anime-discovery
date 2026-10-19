import unittest
from anime_auto_approval import decide_episode

class PolicyTests(unittest.TestCase):
    def test_automatic(self):
        shadow = {'policy': {'enabled': True, 'auto_approve_threshold': 90}, 'score_points': 95, 'decision': 'SHADOW_HIGH_CONFIDENCE', 'blockers': []}
        episode = {'decision': 'AUTO_VERIFIED_CANDIDATE', 'episode_identity_verified': True, 'blockers': [], 'proposed_mapping': {'tvdb_id': '123', 'tvdb_season': 1, 'tvdb_episode': 2}}
        self.assertEqual(decide_episode(shadow, episode)['decision'], 'AUTO_APPROVED')
        self.assertEqual(decide_episode(shadow, episode, series_blocked=True)['decision'], 'BLOCKED')
        episode['episode_identity_verified'] = False
        self.assertEqual(decide_episode(shadow, episode)['decision'], 'NEEDS_REVIEW')

if __name__ == '__main__':
    unittest.main()
