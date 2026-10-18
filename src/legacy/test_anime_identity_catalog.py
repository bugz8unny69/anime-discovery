import unittest
from anime_identity_catalog import audit

class AuditTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(audit({})['issues'],[])
    def test_conflict(self):
        report=audit({'1':{'anidb_id':'123','tvdb_id':'456'},'2':{'anidb_id':'123','tvdb_id':'999'}})
        self.assertTrue(any('conflicts' in x for x in report['issues']))
    def test_no_implicit_approval(self):
        report=audit({'3':{'anidb_id':'1','tvdb_id':'2','usable_for_automation':True}})
        self.assertFalse(report['records'][0]['usable_for_automation'])
        self.assertTrue(report['issues'])
    def test_duplicates_allowed(self):
        report=audit({'1':{'anidb_id':'123','tvdb_id':'456'},'2':{'anidb_id':'123','tvdb_id':'456'}})
        self.assertEqual(report['unique_pairs'],1)
        self.assertEqual(report['issues'],[])
    def test_bad_id(self):
        self.assertTrue(audit({'1':{'anidb_id':'0','tvdb_id':'456'}})['issues'])

if __name__=='__main__': unittest.main()
