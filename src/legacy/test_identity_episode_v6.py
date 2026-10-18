import unittest
from anime_identity_episode_v6 import inspect, extract_episodes

class EpisodeTests(unittest.TestCase):
    def base(self, offset=None, rules=None):
        return {'episode_audit':[{'anidb_id':'17495','tvdb_id':'389597','default_tvdb_season':'1', 'episode_candidate':1,'episode_offset':offset,'episode_specific_rules':rules or [],'series_mapping_corroborated':True}], 'issues':[]}
    def test_missing_offset_never_verified(self):
        r=inspect(self.base(),lambda tid,page:{'data':{'episodes':[{'id':12,'seasonNumber':1,'number':1,'name':'Episode 1'}]},'links':{'next':None}})
        self.assertTrue(r['tvdb_episode_checks'][0]['tvdb_episode_exists_at_same_number'])
        self.assertFalse(r['tvdb_episode_checks'][0]['anidb_episode_mapping_verified'])
        self.assertIn('UNRESOLVED',r['next_action'])
    def test_absent_episode(self):
        r=inspect(self.base(),lambda *_:{'data':{'episodes':[]}})
        self.assertIn('NOT_FOUND',r['next_action'])
    def test_error(self):
        def fail(*_): raise TimeoutError('offline')
        r=inspect(self.base(),fail)
        self.assertEqual(r['next_action'],'RETRY_TVDB_EPISODES; NO_STATUS_CHANGE')
    def test_pagination(self):
        def fetch(_,page):
            return {'data':{'episodes':[] if page==0 else [{'id':1,'seasonNumber':1,'number':1}]},'links':{'next':'next' if page==0 else None}}
        r=inspect(self.base(),fetch)
        self.assertEqual(r['tvdb_episode_checks'][0]['pages_fetched'],2)
    def test_no_mapping(self):
        r=inspect({'episode_audit':[],'issues':[]},lambda *_:None)
        self.assertEqual(r['next_action'],'RETRY_OR_REVIEW_MAPPING; NO_STATUS_CHANGE')
    def test_explicit_offset_not_automatic(self):
        r=inspect(self.base(offset='0'),lambda *_:{'data':{'episodes':[{'seasonNumber':1,'number':1}]}})
        self.assertFalse(r['verified_identity'])
        self.assertFalse(r['usable_for_automation'])
    def test_extract_list(self):
        self.assertEqual(len(extract_episodes({'data':[{'id':1}]})),1)

if __name__=='__main__': unittest.main()
