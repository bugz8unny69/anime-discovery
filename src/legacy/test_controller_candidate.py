import ast, tempfile, unittest
from pathlib import Path
from build_controller_candidate import build

SOURCE=Path(__file__).with_name('api.py')

class CandidateTests(unittest.TestCase):
    def test_syntax(self): ast.parse(SOURCE.read_text())
    def test_guard_generated(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'candidate.py';build(SOURCE,dest)
            self.assertIn('if data.status in ("APPROVED", "REJECTED"):',dest.read_text())
            self.assertIn('raise HTTPException(403',dest.read_text())
    def test_no_inplace(self):
        with self.assertRaises(ValueError): build(SOURCE,SOURCE)
    def test_no_duplicate_patch(self):
        with tempfile.TemporaryDirectory() as d:
            first=Path(d)/'first.py';build(SOURCE,first)
            with self.assertRaises(ValueError):build(first,Path(d)/'second.py')
    def test_existing_routes_retained(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'candidate.py';build(SOURCE,dest)
            def routes(path):
                t=ast.parse(path.read_text());return [(n.name,ast.dump(dec)) for n in t.body if isinstance(n,ast.FunctionDef) for dec in n.decorator_list if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.value.id=='app']
            self.assertEqual(routes(SOURCE),routes(dest))
    def test_production_path_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'candidate.py';build(SOURCE,dest)
            self.assertIn('DB = "/var/lib/anime-discovery/controller.db"',dest.read_text())
    def test_legacy_review_not_removed(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'candidate.py';build(SOURCE,dest)
            self.assertIn('"NEEDS_REVIEW": {"PENDING_REVIEW"}',dest.read_text())

if __name__=='__main__': unittest.main()
