import json
import tempfile
import unittest
from pathlib import Path
from anime_identity_confidence_v14 import load_policy, score

FIXTURE = Path(__file__).with_name('v14-solo-leveling-fixture.json')
class TestConfidence(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(load_policy('/missing/v14-policy.json')['auto_approve_threshold'], 90)
    def test_weights_sum(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.json'; p.write_text(json.dumps({'weights': {'title_match': 20}}))
            with self.assertRaises(ValueError): load_policy(p)
    def test_invalid_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.json'; p.write_text(json.dumps({'auto_approve_threshold': 60, 'review_threshold': 70}))
            with self.assertRaises(ValueError): load_policy(p)
    def test_fixture_high_confidence(self):
        report = json.loads(FIXTURE.read_text())
        result = score(report, load_policy('/missing/v14-policy.json'))
        self.assertEqual(result['decision'], 'SHADOW_HIGH_CONFIDENCE')
        self.assertEqual(result['score_points'], 100)
        self.assertFalse(result['eligible_for_acquisition'])
    def test_blockers_override(self):
        report = json.loads(FIXTURE.read_text()); report['release_name'] += ' OVA'
        result = score(report, load_policy('/missing/v14-policy.json'))
        self.assertEqual(result['decision'], 'SHADOW_BLOCKED')
    def test_configurable_threshold(self):
        report = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'policy.json'; p.write_text(json.dumps({'auto_approve_threshold': 100}))
            self.assertEqual(score(report, load_policy(p))['decision'], 'SHADOW_HIGH_CONFIDENCE')
    def test_disabled(self):
        report = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'policy.json'; p.write_text(json.dumps({'enabled': False}))
            self.assertEqual(score(report, load_policy(p))['decision'], 'SHADOW_DISABLED')
if __name__ == '__main__': unittest.main()
