import unittest
from anime_identity_crosscheck import assess

class CrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.a = [{'anidb_id':'17495','titles':['Solo Leveling','Ore dake Level Up na Ken']}]
        self.t = [{'tvdb_id':'389597','name':'Solo Leveling'}]
        self.d = {'389597':{'titles':['Solo Leveling'],'year':'2024'}}

    def test_single_title_match_not_verified(self):
        rows, action = assess(self.a,self.t,self.d,[])
        self.assertTrue(rows[0]['title_corroborated'])
        self.assertFalse(rows[0]['cross_database_link_verified'])
        self.assertEqual(action,'SINGLE_TITLE_CORROBORATION; CROSS_REFERENCE_REQUIRED')

    def test_multiple_matches_are_ambiguous(self):
        t = self.t + [{'tvdb_id':'465668','name':'Solo Leveling'}]
        d = dict(self.d, **{'465668':{'titles':['Solo Leveling'],'year':'2024'}})
        _, action = assess(self.a,t,d,[])
        self.assertEqual(action,'AMBIGUOUS_TITLE_MATCH; DO_NOT_CHANGE_STATUS')

    def test_error_prevents_decision(self):
        _, action = assess(self.a,self.t,self.d,['network failed'])
        self.assertEqual(action,'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS')

    def test_no_match_requires_review(self):
        _, action = assess(self.a,self.t,{'389597':{'titles':['Different Series'],'year':'2024'}},[])
        self.assertEqual(action,'NEEDS_REVIEW_CANDIDATE; DO_NOT_CHANGE_STATUS')

if __name__ == '__main__':
    unittest.main()
