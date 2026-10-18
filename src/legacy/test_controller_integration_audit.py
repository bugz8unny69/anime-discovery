import unittest
from controller_integration_audit import audit_source

SAMPLE = '''
import sqlite3
from fastapi import Depends
TOKEN = "SHOULD_NOT_LEAK_123"
def authenticate(token="SHOULD_NOT_LEAK_456"):
    return token
@app.post("/discover")
def discover(auth=Depends(authenticate)):
    sqlite3.connect("/var/lib/anime-discovery/controller.db")
    return TOKEN
@app.get("/health")
def health(): return {"ok": True}
'''

class AuditTests(unittest.TestCase):
    def setUp(self): self.report=audit_source(SAMPLE)
    def test_routes(self): self.assertEqual(self.report['route_count'],2)
    def test_methods(self): self.assertEqual({r['method'] for r in self.report['routes']},{'GET','POST'})
    def test_auth_not_assumed(self): self.assertTrue(all(r['auth_status']=='UNVERIFIED' for r in self.report['routes']))
    def test_dependency_detected(self): self.assertEqual(self.report['routes'][0]['dependency_markers'],['dependency-call'])
    def test_auth_function(self): self.assertIn('authenticate',self.report['authentication_functions'])
    def test_sqlite_import(self): self.assertTrue(self.report['sqlite_import_detected'])
    def test_no_secrets(self): self.assertNotIn('SHOULD_NOT_LEAK',str(self.report))
    def test_no_db_path(self): self.assertNotIn('/var/lib/anime-discovery',str(self.report))
    def test_not_ready(self): self.assertFalse(self.report['production_ready'])
    def test_dry_run(self): self.assertTrue(self.report['dry_run_only'])
    def test_empty_source(self): self.assertEqual(audit_source('')['route_count'],0)
    def test_invalid_source(self):
        with self.assertRaises(SyntaxError): audit_source('def broken(')
    def test_dynamic_path(self):
        result=audit_source('@app.get(PATH)\ndef test(): pass')
        self.assertEqual(result['routes'][0]['path'],'<dynamic>')
    def test_not_executed(self):
        result=audit_source('raise RuntimeError("must not execute")')
        self.assertTrue(result['source_parsed'])

if __name__=='__main__': unittest.main()
