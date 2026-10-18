import unittest
from anime_identity_crosscheck_v3 import classify_tvdb, explicit_anidb_ids, decide

class Tests(unittest.TestCase):
    def test_animation(self):
        self.assertEqual(classify_tvdb({'genres':[{'name':'Animation'}]})[0], 'ANIMATION')
    def test_unknown_not_assumed(self):
        self.assertEqual(classify_tvdb({'name':'Solo Leveling'})[0], 'UNKNOWN')
    def test_live_action(self):
        self.assertEqual(classify_tvdb({'type':{'name':'Live Action'}})[0], 'LIVE_ACTION')
    def test_remote_link(self):
        self.assertEqual(explicit_anidb_ids({'remoteIds':[{'sourceName':'AniDB','id':'17495'}]}), ['17495'])
    def test_url_is_not_link(self):
        self.assertEqual(explicit_anidb_ids({'remoteIds':[{'sourceName':'Other','id':'17495'}]}), [])
    def test_single_plausible_not_verified(self):
        row = {'title_corroborated':True,'media_type':'ANIMATION','explicit_anidb_link':False,'explicit_anidb_conflict':False}
        self.assertEqual(decide([row],[]), 'SINGLE_PLAUSIBLE_ANIME; CROSS_REFERENCE_REQUIRED')
    def test_explicit_link_still_requires_audit(self):
        row = {'title_corroborated':True,'media_type':'ANIMATION','explicit_anidb_link':True,'explicit_anidb_conflict':False}
        self.assertEqual(decide([row],[]), 'EXPLICIT_LINK_AND_ANIMATION_CORROBORATED; MANUAL_AUDIT_REQUIRED')
    def test_errors_block(self):
        self.assertEqual(decide([],['network']), 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS')

if __name__ == '__main__':
    unittest.main()
