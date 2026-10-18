import tempfile
import unittest
from pathlib import Path
from production_readiness_audit import audit, CHECKS

class ReadinessAuditTests(unittest.TestCase):
    def test_current_modules_found(self):
        report = audit()
        self.assertTrue(all(item['status'] == 'FOUND' for item in report['inventory']), report['inventory'])
    def test_no_false_production_ready(self):
        report = audit()
        self.assertFalse(report['production_ready'])
        self.assertTrue(report['dry_run_only'])
        self.assertTrue(all(g['status'] != 'PASS' for g in report['release_gates']))
    def test_missing_modules_fail_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = audit(Path(tmp))
            self.assertEqual(len(report['inventory']), len(CHECKS))
            self.assertTrue(all(i['status'] == 'MISSING' for i in report['inventory']))
    def test_syntax_error_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, CHECKS[0][0]).write_text('def bad(:\n')
            report = audit(Path(tmp))
            self.assertTrue(report['inventory'][0]['status'].startswith('UNREADABLE:'))
    def test_does_not_import_project_modules(self):
        import ast
        tree = ast.parse(Path(__file__).with_name('production_readiness_audit.py').read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(names, {'ast','json'})
    def test_gate_priorities(self):
        self.assertTrue(all(g['priority'] in ('P0','P1') for g in audit()['release_gates']))

if __name__ == '__main__':
    unittest.main(verbosity=2)
