import copy
import json
import unittest
from pathlib import Path
from controller_integration_plan import build_plan

AUDIT = json.loads((Path(__file__).parent / 'anime-controller-audit.json').read_text())


class IntegrationPlanTests(unittest.TestCase):
    def test_real_audit(self):
        self.assertEqual(build_plan(AUDIT)['source_route_count'], 17)

    def test_not_ready(self):
        self.assertFalse(build_plan(AUDIT)['production_ready'])

    def test_no_auto_approval(self):
        self.assertFalse(build_plan(AUDIT)['auto_mapping_approval_enabled'])

    def test_no_cancellation(self):
        self.assertFalse(build_plan(AUDIT)['live_cancellation_enabled'])

    def test_deterministic(self):
        self.assertEqual(build_plan(AUDIT), build_plan(AUDIT))

    def test_reject_wrong_format(self):
        d = copy.deepcopy(AUDIT); d['format'] = 'unknown'
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_missing_routes(self):
        d = copy.deepcopy(AUDIT); d['routes'] = []
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_bad_count(self):
        d = copy.deepcopy(AUDIT); d['route_count'] = 99
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_duplicate(self):
        d = copy.deepcopy(AUDIT); d['routes'][1] = d['routes'][0]
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_missing_critical(self):
        d = copy.deepcopy(AUDIT)
        d['routes'] = [r for r in d['routes'] if r['path'] != '/series/{sid}/review']
        d['route_count'] = len(d['routes'])
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_unparsed(self):
        d = copy.deepcopy(AUDIT); d['source_parsed'] = False
        with self.assertRaises(ValueError): build_plan(d)

    def test_reject_unknown_auth(self):
        d = copy.deepcopy(AUDIT); d['routes'][0]['auth_status'] = 'SECURE'
        with self.assertRaises(ValueError): build_plan(d)

    def test_review_not_assumed_secure(self):
        plan = build_plan(AUDIT)
        review = next(r for r in plan['route_reviews'] if r['path'] == '/series/{sid}/review')
        self.assertEqual(review['auth_observed'], 'UNVERIFIED')
        self.assertEqual(review['review'], 'WRITE_REQUIRES_AUTH_REVIEW')

    def test_stages_include_rollback(self):
        self.assertIn('rollback', str(build_plan(AUDIT)['stages']).lower())

    def test_no_secrets_or_env(self):
        output = json.dumps(build_plan(AUDIT))
        self.assertNotIn('ANIME_DISCOVERY_TOKEN', output)
        self.assertNotIn('/etc/anime-discovery/api.env', output)

    def test_readonly_audit_unchanged(self):
        before = copy.deepcopy(AUDIT)
        build_plan(AUDIT)
        self.assertEqual(AUDIT, before)


if __name__ == '__main__':
    unittest.main()
