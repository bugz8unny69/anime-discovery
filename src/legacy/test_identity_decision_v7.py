import unittest
from anime_identity_decision_v7 import decide

class Tests(unittest.TestCase):
    def base(self):
        return {'notification_id':1,'audit_version':6,'status_unchanged':'UNTRUSTED',
                'mapping_evidence':[{'anidb_id':'17495','tvdb_id':'389597','anime_lists_pair_match':True,'media_type':'ANIMATION','title_corroborated':True}],
                'episode_audit':[{'anidb_id':'17495','tvdb_id':'389597','episode_offset':None,'episode_specific_rules':[]}],
                'tvdb_episode_checks':[{'tvdb_id':'389597','tvdb_episode_exists_at_same_number':True}]}
    def test_verified_series_not_episode(self):
        r=decide(self.base()); self.assertTrue(r['series_identity_verified']); self.assertFalse(r['episode_identity_verified']); self.assertFalse(r['eligible_for_acquisition'])
    def test_conflict(self):
        x=self.base(); x['episode_audit'][0]['tvdb_id']='999'; self.assertFalse(decide(x)['series_identity_verified'])
    def test_duplicate(self):
        x=self.base(); x['mapping_evidence']*=2; self.assertFalse(decide(x)['series_identity_verified'])
    def test_lookup_issue(self):
        x=self.base(); x['issues']=['timeout']; self.assertFalse(decide(x)['series_identity_verified'])
    def test_episode_absent(self):
        x=self.base(); x['tvdb_episode_checks']=[]; self.assertIn('TVDB_EPISODE_NOT_CONFIRMED', decide(x)['issues'])
    def test_explicit_offset_not_sufficient(self):
        x=self.base(); x['episode_audit'][0]['episode_offset']='0'; self.assertFalse(decide(x)['episode_identity_verified'])

if __name__ == '__main__': unittest.main()
