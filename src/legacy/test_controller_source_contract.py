import unittest
from pathlib import Path
from controller_source_contract import inspect

API=Path(__file__).with_name('api.py')
class SourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=inspect(API.read_text())
    def test_routes(self): self.assertEqual(self.report['route_count'],17)
    def test_auth(self): self.assertTrue(self.report['all_non_health_routes_declare_discovery_token'])
    def test_health(self): self.assertTrue(self.report['health_public'])
    def test_review_auth(self): self.assertTrue(self.report['review_uses_discovery_token'])
    def test_review_approval(self): self.assertTrue(self.report['review_allows_approved_transition'])
    def test_waits(self): self.assertTrue(self.report['readiness_waits_for_reserved_zero'])
    def test_weak_verify(self): self.assertFalse(self.report['verify_staged_calls_dual_audio_probe'])
    def test_strong_check(self): self.assertTrue(self.report['stronger_staged_check_calls_dual_audio_probe'])
    def test_transaction(self): self.assertTrue(self.report['database_has_immediate_transaction'])
    def test_rollback(self): self.assertTrue(self.report['database_has_rollback'])
    def test_not_ready(self): self.assertFalse(self.report['production_ready'])
    def test_missing_auth_fixture(self):
        s='from fastapi import FastAPI\napp=FastAPI()\n@app.post("/write")\ndef write(): pass'
        self.assertFalse(inspect(s)['all_non_health_routes_declare_discovery_token'])
    def test_empty_source(self): self.assertEqual(inspect('')['route_count'],0)
    def test_syntax_error(self):
        with self.assertRaises(SyntaxError):inspect('def invalid(')

if __name__=='__main__':unittest.main()
