import tempfile
import unittest
from pathlib import Path
from anime_identity_audit_v5 import audit, write_json_atomic

BASE = {'issues': [], 'episode_candidate': 1, 'crosscheck_v3': [
    {'anidb_id': '17495', 'tvdb_id': '389597', 'media_type': 'ANIMATION', 'title_corroborated': True}
]}


def xml(attrs='', mapping=''):
    return f'<anime-list><anime anidbid="17495" tvdbid="389597" defaulttvdbseason="1" {attrs}>{mapping}</anime></anime-list>'.encode()


class AuditTests(unittest.TestCase):
    def test_missing_offset_requires_audit(self):
        r = audit(BASE, xml())
        self.assertIn('EPISODE_OFFSET_NOT_EXPLICIT', r['episode_audit'][0]['audit_flags'])
        self.assertFalse(r['verified_identity'])

    def test_explicit_offset_is_not_episode_verification(self):
        r = audit(BASE, xml('episodeoffset="0"'))
        self.assertEqual(r['episode_audit'][0]['mapped_tvdb_episode_if_explicit'], 1)
        self.assertFalse(r['episode_audit'][0]['episode_mapping_verified'])
        self.assertIn('TVDB_EPISODE_EXISTENCE', r['next_action'])

    def test_specific_rules_flagged(self):
        r = audit(BASE, xml('episodeoffset="0"', '<mapping-list><mapping anidbseason="1" tvdbseason="2">1-12;1-12</mapping></mapping-list>'))
        self.assertIn('EPISODE_SPECIFIC_MAPPING_REQUIRES_AUDIT', r['episode_audit'][0]['audit_flags'])

    def test_bad_episode(self):
        r = audit(dict(BASE, episode_candidate=None), xml('episodeoffset="0"'))
        self.assertIn('EPISODE_NOT_POSITIVE_INTEGER', r['episode_audit'][0]['audit_flags'])

    def test_no_mapping(self):
        r = audit(BASE, b'<anime-list/>')
        self.assertEqual(r['episode_audit'], [])
        self.assertFalse(r['verified_identity'])

    def test_atomic_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'sub' / 'report.json'
            write_json_atomic(p, {'a': 1})
            self.assertEqual(p.read_text().strip(), '{\n  "a": 1\n}')

if __name__ == '__main__':
    unittest.main()
